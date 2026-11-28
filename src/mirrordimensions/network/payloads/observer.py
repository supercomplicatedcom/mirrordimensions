# SPDX-License-Identifier: Apache-2.0
"""The browser observer. It runs in its own container that shares the managed browser's
network namespace (decision 0014), and does two things:

1. Passes the agent's DevTools connection through to the browser, unchanged, byte for byte.
   It listens on the browser's office address; the browser itself listens on loopback only.
   A copy of what the agent sends is decoded and recorded: every DevTools command, which
   is every way the agent can act on the browser.
2. Holds a second, read-only DevTools session on loopback that records navigations and
   takes screenshots. It sends no command that changes a page, injects no script and
   enables nothing the page can read.

Standard library only. Events go to standard output as JSON lines; nothing listens except
the pass-through. Configured by /etc/observer/config.json:
  {"listen": "10.40.0.120:9222", "upstream": "127.0.0.1:9222", "secrets": ["..."],
   "screenshot_every_s": 1.0}
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import os
import struct
import sys
import time
import urllib.request
import zlib
from typing import Any

CONFIG = "/etc/observer/config.json"
MAX_PARAMS = 400  # characters of a command's parameters kept in an event
REDACTED = "[redacted]"
SETTLE_S = 0.3  # quiet time after a load or input before a page is photographed

_secrets: list[str] = []


def emit(kind: str, data: dict[str, Any]) -> None:
    line = json.dumps({"source": "browser", "type": kind, "data": data, "t": time.time()})
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def redact(text: str) -> str:
    for secret in _secrets:
        if secret:
            text = text.replace(secret, REDACTED)
    return text


# -- WebSocket frames (RFC 6455), enough to read both directions and to talk as a client ----


class FrameReader:
    """Reassembles messages from a byte stream that is also being passed through."""

    def __init__(self) -> None:
        self.buffer = b""
        self.parts: list[bytes] = []
        self.opcode = 0
        self.compressed = False

    def feed(self, data: bytes) -> list[tuple[int, bytes, bool]]:
        """Complete messages: (opcode, payload, compressed with permessage-deflate)."""
        self.buffer += data
        messages: list[tuple[int, bytes, bool]] = []
        while True:
            frame = self._frame()
            if frame is None:
                return messages
            fin, rsv1, opcode, payload = frame
            if opcode in (1, 2):  # text or binary: the start of a message
                self.opcode, self.parts, self.compressed = opcode, [payload], rsv1
            elif opcode == 0:  # continuation
                self.parts.append(payload)
            else:  # control frames (close, ping, pong) stand alone
                messages.append((opcode, payload, False))
                continue
            if fin:
                messages.append((self.opcode, b"".join(self.parts), self.compressed))
                self.parts = []

    def _frame(self) -> tuple[bool, bool, int, bytes] | None:
        buf = self.buffer
        if len(buf) < 2:
            return None
        fin, rsv1, opcode = bool(buf[0] & 0x80), bool(buf[0] & 0x40), buf[0] & 0x0F
        masked, length = bool(buf[1] & 0x80), buf[1] & 0x7F
        offset = 2
        if length == 126:
            if len(buf) < 4:
                return None
            length = struct.unpack(">H", buf[2:4])[0]
            offset = 4
        elif length == 127:
            if len(buf) < 10:
                return None
            length = struct.unpack(">Q", buf[2:10])[0]
            offset = 10
        mask = b""
        if masked:
            if len(buf) < offset + 4:
                return None
            mask = buf[offset : offset + 4]
            offset += 4
        if len(buf) < offset + length:
            return None
        payload = buf[offset : offset + length]
        self.buffer = buf[offset + length :]
        if masked:
            payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        return fin, rsv1, opcode, payload


def client_frame(text: str) -> bytes:
    payload = text.encode()
    mask = os.urandom(4)
    header = bytes([0x81])
    if len(payload) < 126:
        header += bytes([0x80 | len(payload)])
    elif len(payload) < 65536:
        header += bytes([0x80 | 126]) + struct.pack(">H", len(payload))
    else:
        header += bytes([0x80 | 127]) + struct.pack(">Q", len(payload))
    return header + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(payload))


# -- 1. the agent's connection, passed through and recorded --------------------------------

INPUT = ("Input.",)
NAVIGATE = ("Page.navigate", "Page.reload", "Page.navigateToHistoryEntry")


def summarize(params: Any) -> str:
    text = json.dumps(params, separators=(",", ":"), sort_keys=True)
    text = redact(text)
    return text if len(text) <= MAX_PARAMS else text[:MAX_PARAMS] + "..."


class AgentStream:
    """Decodes a copy of one direction of the agent's connection."""

    def __init__(self, conn: int, peer: str, on_activity: Any = None) -> None:
        self.conn, self.peer = conn, peer
        self.on_activity = on_activity  # called for input and navigations
        self.head = b""
        self.upgraded = False
        self.frames = FrameReader()
        # permessage-deflate (RFC 7692), as the browser's upgrade response agreed it
        self.inflater = zlib.decompressobj(-zlib.MAX_WBITS)
        self.no_context_takeover = False
        self.reply_head = b""

    def from_browser(self, data: bytes) -> bool:
        """Look for the browser's upgrade response in what it sends back; return False once
        it is read (after that the stream is frames the observer does not need)."""
        self.reply_head = (self.reply_head + data)[-65536:]
        start = self.reply_head.find(b"HTTP/1.1 101")
        if start < 0 or b"\r\n\r\n" not in self.reply_head[start:]:
            return True
        head = self.reply_head[start:].split(b"\r\n\r\n", 1)[0].lower()
        self.no_context_takeover = b"client_no_context_takeover" in head
        return False

    def _inflate(self, payload: bytes) -> bytes:
        if self.no_context_takeover:
            self.inflater = zlib.decompressobj(-zlib.MAX_WBITS)
        return self.inflater.decompress(payload + b"\x00\x00\xff\xff")

    def from_agent(self, data: bytes) -> None:
        if not self.upgraded:
            self.head += data
            if b"\r\n\r\n" not in self.head:
                return
            request, _, rest = self.head.partition(b"\r\n\r\n")
            line = request.split(b"\r\n", 1)[0].decode("latin-1")
            method, _, target = line.partition(" ")
            path = target.rsplit(" ", 1)[0]
            is_ws = b"upgrade: websocket" in request.lower()
            emit(
                "browser.connect",
                {
                    "conn": self.conn,
                    "client": self.peer,
                    "method": method,
                    "path": path,
                    "websocket": is_ws,
                },
            )
            self.head = b""
            if not is_ws:
                if rest:
                    self.from_agent(rest)  # keep-alive: the next request
                return
            self.upgraded = True
            data = rest
        for opcode, payload, compressed in self.frames.feed(data):
            if opcode != 1:
                continue
            try:
                message = json.loads(self._inflate(payload) if compressed else payload)
            except (ValueError, zlib.error) as exc:
                emit(
                    "browser.action",
                    {"conn": self.conn, "undecoded": len(payload), "error": str(exc)[:120]},
                )
                continue
            if not isinstance(message, dict) or "method" not in message:
                continue
            method = str(message["method"])
            if self.on_activity is not None and method.startswith((*INPUT, *NAVIGATE)):
                self.on_activity()  # input or a navigation: the page is about to change
            emit(
                "browser.action",
                {
                    "conn": self.conn,
                    "client": self.peer,
                    "session": message.get("sessionId", ""),
                    "id": message.get("id"),
                    "method": method,
                    "kind": "input"
                    if method.startswith(INPUT)
                    else "navigate"
                    if method in NAVIGATE
                    else "command",
                    "params": summarize(message.get("params", {})),
                },
            )


async def pipe(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    tap: AgentStream,
    from_agent: bool,
) -> None:
    reading_replies = True
    try:
        while True:
            data = await reader.read(65536)
            if not data:
                break
            writer.write(data)
            if from_agent or reading_replies:
                try:
                    if from_agent:
                        tap.from_agent(data)
                    else:
                        reading_replies = tap.from_browser(data)
                except Exception as exc:  # noqa: BLE001 (recording must never break the agent's session)
                    emit("browser.observer_error", {"where": "tap", "error": str(exc)[:200]})
            await writer.drain()
    except (ConnectionError, asyncio.IncompleteReadError):
        pass
    finally:
        with contextlib.suppress(Exception):
            writer.close()


_conn_counter = 0


async def serve_agent(upstream: tuple[str, int], listen: tuple[str, int], on_activity: Any) -> None:
    async def handle(agent_r: asyncio.StreamReader, agent_w: asyncio.StreamWriter) -> None:
        global _conn_counter
        _conn_counter += 1
        peer = str(agent_w.get_extra_info("peername")[0])
        try:
            browser_r, browser_w = await asyncio.open_connection(*upstream)
        except OSError:
            agent_w.close()  # as the browser would: the connection is refused or reset
            return
        tap = AgentStream(_conn_counter, peer, on_activity)
        await asyncio.gather(
            pipe(agent_r, browser_w, tap, True), pipe(browser_r, agent_w, tap, False)
        )
        emit("browser.disconnect", {"conn": tap.conn, "client": peer})

    server = await asyncio.start_server(handle, *listen)
    async with server:
        await server.serve_forever()


# -- 2. the read-only observer session ---------------------------------------------------


class Observer:
    def __init__(self, upstream: tuple[str, int], every_s: float) -> None:
        self.upstream = upstream
        self.every_s = every_s
        self.next_id = 0
        self.waiting: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self.sessions: dict[str, str] = {}  # session -> target
        self.urls: dict[str, str] = {}  # target -> current URL
        self.dirty: dict[str, float] = {}  # session -> when it last changed (unscreenshotted)
        self.last_shot: dict[str, float] = {}
        self.attaching: set[str] = set()
        self.tasks: set[asyncio.Task[None]] = set()
        self.writer: asyncio.StreamWriter | None = None

    async def run(self) -> None:
        while True:
            with contextlib.suppress(
                OSError, ConnectionError, asyncio.IncompleteReadError, ValueError
            ):
                await self._session()
            await asyncio.sleep(0.5)  # the browser is starting or restarting

    async def _session(self) -> None:
        host, port = self.upstream
        with urllib.request.urlopen(f"http://{host}:{port}/json/version", timeout=5) as resp:
            ws_url = json.loads(resp.read())["webSocketDebuggerUrl"]
        path = "/" + ws_url.split("/", 3)[3]
        reader, writer = await asyncio.open_connection(host, port)
        key = base64.b64encode(os.urandom(16)).decode()
        writer.write(
            f"GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\nUpgrade: websocket\r\n"
            f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n".encode()
        )
        await writer.drain()
        head = await reader.readuntil(b"\r\n\r\n")
        if b" 101 " not in head.split(b"\r\n", 1)[0]:
            raise ConnectionError("no upgrade")
        self.writer = writer
        frames = FrameReader()
        reading = asyncio.create_task(self._read(reader, frames))
        shooting = asyncio.create_task(self._screenshots())
        try:
            await self.call("Target.setDiscoverTargets", {"discover": True})
            for target in (await self.call("Target.getTargets", {})).get("targetInfos", []):
                await self._attach(target)
            await reading
        finally:
            shooting.cancel()
            reading.cancel()
            self.writer = None
            self.sessions.clear()
            self.attaching.clear()

    async def call(
        self, method: str, params: dict[str, Any], session: str | None = None
    ) -> dict[str, Any]:
        if self.writer is None:
            raise ConnectionError("not connected")
        self.next_id += 1
        message: dict[str, Any] = {"id": self.next_id, "method": method, "params": params}
        if session:
            message["sessionId"] = session
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self.waiting[self.next_id] = future
        self.writer.write(client_frame(json.dumps(message)))
        await self.writer.drain()
        return await asyncio.wait_for(future, timeout=15)

    async def _attach(self, target: dict[str, Any]) -> None:
        """Attach to a page only once the agent has: a target's `attached` flag is visible
        to any DevTools client, so attaching first would change what the agent sees."""
        target_id = target["targetId"]
        if (
            target.get("type") != "page"
            or not target.get("attached")
            or target_id in self.attaching
            or target_id in self.sessions.values()
        ):
            return
        self.attaching.add(target_id)
        try:
            result = await self.call(
                "Target.attachToTarget", {"targetId": target_id, "flatten": True}
            )
        finally:
            self.attaching.discard(target_id)
        session = result["sessionId"]
        self.sessions[session] = target["targetId"]
        await self.call("Page.enable", {}, session)
        self.dirty[session] = time.monotonic()

    async def _read(self, reader: asyncio.StreamReader, frames: FrameReader) -> None:
        while True:
            data = await reader.read(1 << 20)
            if not data:
                return
            for opcode, payload, _ in frames.feed(data):
                if opcode == 8:
                    return
                if opcode == 1:
                    self._message(json.loads(payload))

    def _message(self, message: dict[str, Any]) -> None:
        if "id" in message:
            future = self.waiting.pop(message["id"], None)
            if future is not None and not future.done():
                if "error" in message:
                    future.set_exception(RuntimeError(json.dumps(message["error"])[:200]))
                else:
                    future.set_result(message.get("result", {}))
            return
        method, params = message.get("method"), message.get("params", {})
        session = message.get("sessionId", "")
        if method in ("Target.targetCreated", "Target.targetInfoChanged"):
            self._spawn(self._attach(params["targetInfo"]))
        elif method == "Target.targetDestroyed":
            for gone in [k for k, v in self.sessions.items() if v == params["targetId"]]:
                del self.sessions[gone]
                self.dirty.pop(gone, None)
            emit("browser.target", {"target": params["targetId"], "event": "closed"})
        elif method == "Page.frameNavigated" and session in self.sessions:
            frame = params["frame"]
            if frame.get("parentId"):
                return  # an embedded frame; its requests reach the gateway anyway
            target = self.sessions[session]
            url = redact(frame.get("url", ""))
            self.urls[target] = url
            emit("browser.navigate", {"target": target, "url": url})
            self.dirty[session] = time.monotonic()
        elif method == "Page.loadEventFired" and session in self.sessions:
            # A loaded page is photographed at once: a fast agent may leave it within ms.
            self.dirty.pop(session, None)
            self._spawn(self._shoot(session, self.sessions[session]))

    def _spawn(self, work: Any) -> None:
        task: asyncio.Task[None] = asyncio.create_task(work)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def _screenshots(self) -> None:
        """A screenshot of each page once it has settled after a change: no navigation, load
        or agent command for `SETTLE_S`, and at least `every_s` since its last screenshot."""
        while True:
            await asyncio.sleep(0.2)
            now = time.monotonic()
            for session, changed in list(self.dirty.items()):
                if (
                    now - changed < SETTLE_S
                    or now - self.last_shot.get(session, 0.0) < self.every_s
                ):
                    continue
                del self.dirty[session]
                target = self.sessions.get(session)
                if target is None:
                    continue
                await self._shoot(session, target)

    async def _shoot(self, session: str, target: str) -> None:
        if not self.urls.get(target):
            return  # a tab that never navigated: the browser's blank start page
        started = time.monotonic()
        self.last_shot[session] = started
        try:
            shot = await self.call(
                "Page.captureScreenshot", {"format": "jpeg", "quality": 60}, session
            )
        except Exception as exc:  # noqa: BLE001 (a failed screenshot is recorded, not fatal)
            if session in self.sessions:  # a page closed mid-screenshot is not an error
                emit(
                    "browser.observer_error",
                    {"where": "screenshot", "error": repr(exc)[:200]},
                )
            return
        if not shot.get("data"):  # mid-navigation: try again when it settles
            self.dirty.setdefault(session, time.monotonic())
            return
        emit(
            "browser.screenshot",
            {"target": target, "url": self.urls.get(target, ""), "jpeg": shot["data"]},
        )

    def note_activity(self) -> None:
        now = time.monotonic()
        self.dirty.update(dict.fromkeys(self.sessions, now))


async def main() -> None:
    with open(CONFIG, encoding="utf-8") as handle:
        config = json.load(handle)
    _secrets.extend(sorted(config.get("secrets", []), key=len, reverse=True))
    up_host, up_port = config["upstream"].rsplit(":", 1)
    ls_host, ls_port = config["listen"].rsplit(":", 1)
    upstream = (up_host, int(up_port))
    observer = Observer(upstream, float(config.get("screenshot_every_s", 2.0)))
    emit("browser.observer_ready", {"listen": config["listen"]})
    # Agent commands can change a page without a navigation: each marks pages for a screenshot.
    await asyncio.gather(
        serve_agent(upstream, (ls_host, int(ls_port)), observer.note_activity), observer.run()
    )


if __name__ == "__main__":
    asyncio.run(main())
