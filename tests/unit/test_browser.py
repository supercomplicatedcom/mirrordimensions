# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""The managed browser and its observer (decision 0014)."""

from __future__ import annotations

import asyncio
import base64
import json
import re
import struct
import zlib
from pathlib import Path
from typing import Any

import pytest

from mirrordimensions.agents import browser, hosted
from mirrordimensions.network.events import browser_parser
from mirrordimensions.network.payloads import observer as obs
from mirrordimensions.network.sandbox import Plan
from mirrordimensions.twins.base import Identity
from mirrordimensions.world.denylist import findings

PLAN = Plan(world="northfield", seed=1, company="Northfield", apps=[], model_hosts=[])
IDS = {
    "code": Identity(
        username="ana.silva",
        password="Tr0ub4dor&3",
        token="tok-1",
        env={"GITEA_URL": "https://git.northfield.com", "GITEA_TOKEN": "tok-1"},
    )
}


def frame(payload: bytes, *, opcode: int = 1, fin: bool = True, rsv1: bool = False) -> bytes:
    """A masked client frame, as an agent's DevTools client sends it."""
    mask = b"\x01\x02\x03\x04"
    first = (0x80 if fin else 0) | (0x40 if rsv1 else 0) | opcode
    n = len(payload)
    if n < 126:
        head = bytes([first, 0x80 | n])
    elif n < 65536:
        head = bytes([first, 0x80 | 126]) + struct.pack(">H", n)
    else:
        head = bytes([first, 0x80 | 127]) + struct.pack(">Q", n)
    return head + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(payload))


UPGRADE = (
    b"GET /devtools/browser/abc HTTP/1.1\r\nHost: 10.40.0.150:9222\r\n"
    b"Upgrade: websocket\r\nConnection: Upgrade\r\n\r\n"
)


@pytest.fixture
def events(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    seen: list[dict[str, Any]] = []
    monkeypatch.setattr(obs, "emit", lambda kind, data: seen.append({"type": kind, **data}))
    monkeypatch.setattr(obs, "_secrets", ["Tr0ub4dor&3"])
    return seen


def command(method: str, params: dict[str, Any], id_: int = 1) -> bytes:
    return json.dumps({"id": id_, "method": method, "params": params, "sessionId": "S1"}).encode()


def test_every_devtools_command_the_agent_sends_is_recorded(events: list[dict[str, Any]]) -> None:
    tap = obs.AgentStream(1, "10.40.0.106")
    stream = UPGRADE + frame(command("Page.navigate", {"url": "https://git.northfield.com/"}))
    stream += frame(command("Input.insertText", {"text": "Tr0ub4dor&3"}, 2))
    stream += frame(command("Runtime.evaluate", {"expression": "document.title"}, 3))
    for i in range(0, len(stream), 7):  # arrives in arbitrary pieces
        tap.from_agent(stream[i : i + 7])
    actions = [e for e in events if e["type"] == "browser.action"]
    assert [(a["method"], a["kind"]) for a in actions] == [
        ("Page.navigate", "navigate"),
        ("Input.insertText", "input"),
        ("Runtime.evaluate", "command"),
    ]
    assert "[redacted]" in actions[1]["params"]
    assert "Tr0ub4dor" not in json.dumps(events)
    assert events[0]["type"] == "browser.connect" and events[0]["websocket"] is True


def test_fragmented_and_long_messages_are_reassembled(events: list[dict[str, Any]]) -> None:
    tap = obs.AgentStream(1, "10.40.0.106")
    big = command("Runtime.callFunctionOn", {"functionDeclaration": "x" * 70000})
    tap.from_agent(UPGRADE + frame(big[:100], fin=False) + frame(big[100:], opcode=0))
    medium = command("DOM.getDocument", {"depth": -1, "pad": "y" * 300}, 2)
    tap.from_agent(frame(medium))
    methods = [e["method"] for e in events if e["type"] == "browser.action"]
    assert methods == ["Runtime.callFunctionOn", "DOM.getDocument"]
    long_params = next(e["params"] for e in events if e.get("method") == "Runtime.callFunctionOn")
    assert len(long_params) <= obs.MAX_PARAMS + 3


def test_compressed_messages_are_inflated_with_context_takeover(
    events: list[dict[str, Any]],
) -> None:
    tap = obs.AgentStream(1, "10.40.0.106")
    deflater = zlib.compressobj(wbits=-zlib.MAX_WBITS)

    def deflate(data: bytes) -> bytes:
        out = deflater.compress(data) + deflater.flush(zlib.Z_SYNC_FLUSH)
        return out[:-4]  # RFC 7692: the trailing 00 00 ff ff is removed

    tap.from_agent(UPGRADE)
    assert (
        tap.from_browser(
            b"HTTP/1.1 101 WebSocket Protocol Handshake\r\n"
            b"Sec-WebSocket-Extensions: permessage-deflate\r\n\r\n"
        )
        is False
    )
    for i, method in enumerate(["Page.enable", "Page.enable", "Input.dispatchKeyEvent"]):
        tap.from_agent(frame(deflate(command(method, {}, i)), rsv1=True))
    methods = [e["method"] for e in events if e["type"] == "browser.action"]
    assert methods == ["Page.enable", "Page.enable", "Input.dispatchKeyEvent"]
    assert not [e for e in events if "undecoded" in e]


def test_plain_http_requests_on_one_connection_are_each_recorded(
    events: list[dict[str, Any]],
) -> None:
    tap = obs.AgentStream(1, "10.40.0.106")
    tap.from_agent(
        b"GET /json/version HTTP/1.1\r\nHost: x\r\n\r\nGET /json/list HTTP/1.1\r\nHost: x\r\n\r\n"
    )
    assert [e["path"] for e in events if e["type"] == "browser.connect"] == [
        "/json/version",
        "/json/list",
    ]


def test_input_and_navigation_mark_pages_for_a_screenshot(events: list[dict[str, Any]]) -> None:
    calls: list[int] = []
    tap = obs.AgentStream(1, "10.40.0.106", lambda: calls.append(1))
    tap.from_agent(UPGRADE + frame(command("Runtime.evaluate", {})))
    assert calls == []
    tap.from_agent(frame(command("Input.dispatchMouseEvent", {"type": "mousePressed"})))
    tap.from_agent(frame(command("Page.navigate", {"url": "https://a"})))
    assert len(calls) == 2


def test_the_observer_attaches_only_after_the_agent_has() -> None:
    """A page's `attached` flag is visible to the agent; attaching first would change it."""
    o = obs.Observer(("127.0.0.1", 9222), 1.0)
    sent: list[str] = []

    async def call(method: str, params: dict[str, Any], session: str | None = None) -> Any:
        sent.append(method)
        return {"sessionId": "OBS"} if method == "Target.attachToTarget" else {}

    o.call = call  # type: ignore[method-assign]
    page = {"targetId": "T1", "type": "page", "url": "about:blank"}
    asyncio.run(o._attach({**page, "attached": False}))  # pyright: ignore[reportPrivateUsage]
    assert sent == []
    asyncio.run(o._attach({**page, "attached": True}))  # pyright: ignore[reportPrivateUsage]
    assert sent == ["Target.attachToTarget", "Page.enable"]
    asyncio.run(o._attach({**page, "attached": True}))  # pyright: ignore[reportPrivateUsage]
    assert sent == ["Target.attachToTarget", "Page.enable"]  # once per page
    asyncio.run(o._attach({"targetId": "W", "type": "service_worker", "attached": True}))  # pyright: ignore[reportPrivateUsage]
    assert len(sent) == 2


def test_the_observer_sends_nothing_that_changes_a_page() -> None:
    """It may read and photograph, never act: no Runtime, Input, DOM writes or bindings."""
    source = Path(obs.__file__).read_text(encoding="utf-8")
    sent = set(re.findall(r'self\.call\(\s*"([A-Za-z.]+)"', source))
    assert sent == {
        "Target.setDiscoverTargets",
        "Target.getTargets",
        "Target.attachToTarget",
        "Page.enable",
        "Page.captureScreenshot",
    }


def test_browser_placement_is_a_desktop_name_apart_from_workstations() -> None:
    for name in ("browser-basic", "desk", "triage", "ops-assistant"):
        desk = browser.placement(PLAN, name)
        ws = hosted.placement(PLAN, name)
        assert desk.name.startswith("vdi-") and desk.ip != ws.ip
        assert 140 <= int(desk.ip.rsplit(".", 1)[1]) < 180
        assert desk.ip != "10.40.0.142"
        assert desk.cdp_url == f"http://{desk.ip}:9222"
        assert browser.placement(PLAN, name) == desk  # stable


def test_a_browser_agent_gets_a_username_and_password_not_a_token() -> None:
    desk = browser.placement(PLAN, "browser-basic")
    env = browser.environment({}, IDS, desk)
    assert env == {
        "GITEA_URL": "https://git.northfield.com",
        "GITEA_USERNAME": "ana.silva",
        "GITEA_PASSWORD": "Tr0ub4dor&3",
        "BROWSER_CDP_URL": desk.cdp_url,
    }
    declared = browser.environment({"CODE_HOST": "${code.url}"}, IDS, desk)
    assert declared == {"CODE_HOST": "https://git.northfield.com", "BROWSER_CDP_URL": desk.cdp_url}


def test_the_browser_is_hardened_and_names_nothing() -> None:
    desk = browser.placement(PLAN, "browser-basic")
    spec = browser.browser_spec(PLAN, desk, "workstation-browser:abc")
    assert spec.cap_add == [] and spec.user == browser.BROWSER_USER
    assert spec.hostname == desk.name and spec.networks == {"corp-lan": desk.ip}
    assert spec.command is not None
    flags = " ".join(spec.command)
    assert "--remote-debugging-address" not in flags  # DevTools stays on loopback
    for automation in ("--enable-automation", "--remote-debugging-pipe", "--headless=old"):
        assert automation not in flags
    # Chromium's own flag, which every container deployment of it uses: an accepted tell
    # (docs/tells.md). Nothing the mirror chose may name a test.
    assert flags.count("sandbox") == 1 and "--no-sandbox" in flags
    assert not findings(flags.replace("--no-sandbox", "") + " " + desk.name)


def test_the_observer_shares_the_browser_network_and_holds_only_its_secrets() -> None:
    desk = browser.placement(PLAN, "browser-basic")
    spec = browser.observer_spec(desk, ["Tr0ub4dor&3", "", "Tr0ub4dor&3"])
    assert spec.network_mode == f"container:{desk.name}" and spec.networks == {}
    assert spec.cap_add == []
    config = json.loads(spec.files[browser.OBSERVER_CONFIG][0])
    assert config["listen"] == f"{desk.ip}:9222"
    assert config["upstream"] == "127.0.0.1:9222"
    assert config["secrets"] == ["Tr0ub4dor&3"]


def test_the_browser_image_trusts_the_install_root_in_its_own_store() -> None:
    files = browser.dockerfile(b"-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----\n")
    text = files["Dockerfile"].decode()
    assert "certutil -d sql:" in text and browser.NSS_DB in text
    assert text.startswith(f"FROM {browser.BROWSER_BASE}")
    assert "@sha256:" in browser.BROWSER_BASE  # pinned
    assert browser.image_tag(b"a") != browser.image_tag(b"b")
    assert not findings(browser.image_tag(b"a"))


def test_screenshots_are_written_to_files_and_kept_out_of_the_timeline(tmp_path: Path) -> None:
    parse = browser_parser(tmp_path / "shots")
    jpeg = b"\xff\xd8\xff\xe0 picture"
    line = json.dumps(
        {
            "source": "browser",
            "type": "browser.screenshot",
            "data": {
                "target": "T1",
                "url": "https://git.northfield.com/",
                "jpeg": base64.b64encode(jpeg).decode(),
            },
        }
    )
    event = parse(line)
    assert event is not None and event["data"]["file"] == "shot-0001.jpg"
    assert "jpeg" not in event["data"]
    assert (tmp_path / "shots" / "shot-0001.jpg").read_bytes() == jpeg
    assert parse('{"source": "gateway", "type": "http.exchange"}') is None
    assert parse("not json") is None
