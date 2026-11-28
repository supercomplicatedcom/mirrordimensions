# SPDX-License-Identifier: Apache-2.0
"""The gateway's MQTT listener: TLS on 8883, relayed unchanged to the message broker, with
every connect, subscribe, publish and disconnect recorded both ways (decision 0026).

Standard library only, beside `mqttwire.py`, in the gateway container: the gateway stays
the one component on both the agent's network and the systems' network. A broker is chosen
by the name the client asked for (SNI); an unknown name gets no certificate, as on 443.
Passwords are never recorded, only whether one was sent.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import ssl
import sys
import time
from typing import Any

sys.path.insert(0, "/etc/edge")
import mqttwire

PORT = 8883
ROUTES = "/etc/edge/routes.json"
CERTS = "/etc/edge/certs"
PAYLOAD_LIMIT = 8192


class Routes:
    """Broker hostnames to their address on the systems' network, reloaded when changed."""

    def __init__(self) -> None:
        self.stamp = 0.0
        self.brokers: dict[str, dict[str, str]] = {}
        self.contexts: dict[str, ssl.SSLContext] = {}

    def reload(self) -> None:
        try:
            stamp = os.stat(ROUTES).st_mtime
        except OSError:
            return
        if stamp == self.stamp:
            return
        self.stamp = stamp
        with open(ROUTES, encoding="utf-8") as f:
            self.brokers = dict(json.load(f).get("mqtt", {}))

    def host_of(self, context: ssl.SSLContext | None) -> str:
        """The name a connection asked for: each name has its own context, chosen by SNI."""
        return next((h for h, c in self.contexts.items() if c is context), "")

    def context(self, host: str) -> ssl.SSLContext | None:
        if host not in self.brokers:
            return None
        if host not in self.contexts:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.minimum_version = ssl.TLSVersion.TLSv1_2
            ctx.load_cert_chain(f"{CERTS}/{host}.pem")
            self.contexts[host] = ctx
        return self.contexts[host]


class Capture:
    def __init__(self) -> None:
        self.seq = 0
        self.conns = 0

    def emit(self, kind: str, data: dict[str, Any]) -> None:
        self.seq += 1
        line = {
            "seq": f"mqtt:{self.seq}",
            "ts": time.time(),
            "source": "mqtt",
            "type": kind,
            "data": data,
        }
        sys.stdout.write(json.dumps(line, separators=(",", ":")) + "\n")
        sys.stdout.flush()


def _payload(raw: bytes) -> dict[str, Any]:
    cut = raw[:PAYLOAD_LIMIT]
    try:
        return {"payload": cut.decode("utf-8"), "size": len(raw), "truncated": len(raw) > len(cut)}
    except UnicodeDecodeError:
        return {
            "payload_b64": base64.b64encode(cut).decode(),
            "size": len(raw),
            "truncated": len(raw) > len(cut),
        }


def record(capture: Capture, base: dict[str, Any], packet: mqttwire.Packet, inbound: bool) -> None:
    """One event for a packet that matters to coverage; pings and acks are counted, not kept."""
    f = packet.fields
    kind = packet.kind
    if kind == "connect":
        keep = {
            k: f.get(k)
            for k in ("client_id", "username", "password", "version", "clean", "keepalive")
        }
        capture.emit("mqtt.connect", {**base, **keep})
    elif kind == "connack":
        capture.emit("mqtt.connack", {**base, "code": f.get("code")})
    elif kind in ("subscribe", "unsubscribe"):
        capture.emit(f"mqtt.{kind}", {**base, "topics": f.get("topics", [])})
    elif kind == "suback":
        capture.emit("mqtt.suback", {**base, "codes": f.get("codes", [])})
    elif kind == "publish":
        capture.emit(
            "mqtt.publish",
            {
                **base,
                "direction": "in" if inbound else "out",
                "topic": f.get("topic"),
                "qos": f.get("qos"),
                "retain": f.get("retain"),
                **_payload(f.get("payload", b"")),
            },
        )
    elif kind == "disconnect" and inbound:
        capture.emit("mqtt.disconnect", {**base, "by": "client"})


async def _pump(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    capture: Capture,
    base: dict[str, Any],
    inbound: bool,
    state: dict[str, int],
) -> None:
    buffer = b""
    while True:
        chunk = await reader.read(65536)
        if not chunk:
            break
        buffer += chunk
        packets, buffer = mqttwire.split(buffer)
        for p in packets:
            if p.kind == "connect":
                mqttwire.parse(p)
                state["version"] = int(p.fields.get("version", 4))
            else:
                mqttwire.parse(p, state.get("version", 4))
            record(capture, base, p, inbound)
            writer.write(p.raw)  # exactly the bytes received
        await writer.drain()


async def handle(
    client_r: asyncio.StreamReader, client_w: asyncio.StreamWriter, routes: Routes, capture: Capture
) -> None:
    ssl_obj = client_w.get_extra_info("ssl_object")
    host = routes.host_of(getattr(ssl_obj, "context", None))
    peer = client_w.get_extra_info("peername") or ("", 0)
    capture.conns += 1
    base = {"conn": capture.conns, "client": peer[0], "host": host}
    route = routes.brokers.get(host)
    if not route:
        client_w.close()
        return
    if route.get("visibility") == "denied":
        await _refuse(client_r, client_w, capture, base)
        return
    addr, _, port = str(route["upstream"]).partition(":")
    try:
        broker_r, broker_w = await asyncio.open_connection(addr, int(port or 1883))
    except OSError:
        capture.emit("mqtt.error", {**base, "error": "broker unreachable"})
        client_w.close()
        return
    state: dict[str, int] = {}
    up = asyncio.create_task(_pump(client_r, broker_w, capture, base, True, state))
    down = asyncio.create_task(_pump(broker_r, client_w, capture, base, False, state))
    done, pending = await asyncio.wait({up, down}, return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()
    for task in done:
        exc = task.exception()
        if isinstance(exc, mqttwire.WireError):
            capture.emit("mqtt.error", {**base, "error": str(exc)})
    if up not in done or up.exception() is None:
        capture.emit("mqtt.closed", {**base, "by": "client" if up in done else "broker"})
    for w in (broker_w, client_w):
        w.close()


async def _refuse(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    capture: Capture,
    base: dict[str, Any],
) -> None:
    """A broker the agent is denied: its CONNECT is answered "not authorized", as a broker
    whose access list leaves the user out answers it."""
    buffer = b""
    while True:
        chunk = await reader.read(65536)
        if not chunk:
            writer.close()
            return
        buffer += chunk
        packets, buffer = mqttwire.split(buffer)
        if packets:
            p = mqttwire.parse(packets[0])
            record(capture, base, p, True)
            v5 = p.kind == "connect" and p.fields.get("version") == 5
            writer.write(bytes([0x20, 3, 0, 0x87, 0]) if v5 else bytes([0x20, 2, 0, 5]))
            capture.emit("mqtt.connack", {**base, "code": 0x87 if v5 else 5})
            await writer.drain()
            writer.close()
            return


def tls_context(routes: Routes) -> ssl.SSLContext:
    """The listener's context: the certificate follows the name asked for, or none at all."""
    default = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    default.minimum_version = ssl.TLSVersion.TLSv1_2

    def pick(sock: ssl.SSLObject, name: str | None, _ctx: ssl.SSLContext) -> int | None:
        routes.reload()
        chosen = routes.context(name or "")
        if chosen is None:
            return ssl.ALERT_DESCRIPTION_UNRECOGNIZED_NAME
        sock.context = chosen
        return None

    default.sni_callback = pick
    return default


async def main() -> None:
    routes, capture = Routes(), Capture()
    routes.reload()
    server = await asyncio.start_server(
        lambda r, w: handle(r, w, routes, capture),
        "0.0.0.0",  # noqa: S104 (the gateway's own listener)
        PORT,
        ssl=tls_context(routes),
    )
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
