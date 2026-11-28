# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""M7.5, part 1: the ingress for remote agents (decision 0024). OAuth on the world MCP front,
the relay through the Docker API, the ingress's place in the sandbox, and `world expose`."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import socket
import ssl
import struct
import sys
import threading
from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from mirrordimensions.config.manifest import Manifest
from mirrordimensions.errors import MirrorError
from mirrordimensions.mcp.world import front, toolset
from mirrordimensions.network import ingress_relay, sandbox
from mirrordimensions.world.denylist import findings

REPO = Path(__file__).resolve().parents[2]
EXAMPLE = REPO / "examples" / "mcp" / "eng-tools"
SERVES = {"tools_from": {"file": "tools.json"}, "surfaces": "surfaces.yaml"}
TOKEN = "7c1e" * 10
PASSWORD = "Harbor-lantern-42"

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import portal_fixture  # noqa: E402


def _platform() -> Any:
    spec = importlib.util.spec_from_file_location(
        "platform_ref", REPO / "examples/remote/platform.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def exposed(tmp_path: Path) -> Iterator[str]:
    """The world MCP front, configured as `expose` leaves it, served on a local port."""
    tools = toolset.load(EXAMPLE, "tools", SERVES, {"code", "chat", "tools"})
    server = ThreadingHTTPServer(("127.0.0.1", 0), front.Handler)
    base = f"http://127.0.0.1:{server.server_address[1]}"
    config = toolset.front_config(tools, {"code": "git.rookwood.com", "chat": "chat.rookwood.com"})
    config["tokens"] = {TOKEN: {"person": "tamar.gonzaga", "backends": {}, "tools": None}}
    salt = "a1b2c3"
    config["oauth"] = {
        "issuer": base,
        "company": "Rookwood Outfitters",
        "people": {
            "tamar.gonzaga": {
                "salt": salt,
                "pbkdf2_sha256": front.password_hash(salt, PASSWORD),
                "token": TOKEN,
            }
        },
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    front.Handler.config = front.Config(str(path))
    front.Handler.sessions = {}
    front.Handler.context = ssl.create_default_context()
    front.Handler.oauth = front.OAuthState()
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"{base}/mcp"
    server.shutdown()


def test_a_remote_platform_connects_with_oauth_as_the_specification_requires(exposed: str) -> None:
    platform = _platform().Platform(exposed, None)
    token = platform.connect("tamar.gonzaga", PASSWORD)
    assert token == TOKEN
    auth, init = platform.session(token)
    assert init["serverInfo"]["name"] == "eng-tools"
    listed = platform.call(auth, "tools/list", {}, 2)["result"]["tools"]
    assert "search_issues" in [t["name"] for t in listed]
    assert platform.log[:7] == [
        "POST /mcp -> 401",
        "GET /.well-known/oauth-protected-resource -> 200",
        "GET /.well-known/oauth-authorization-server -> 200",
        "POST /register -> 201",
        "GET /authorize -> 200",
        "POST /authorize -> 302",
        "POST /token -> 200",
    ]


def test_sign_in_refuses_a_wrong_password_and_codes_are_single_use(exposed: str) -> None:
    ref = _platform()
    with pytest.raises(SystemExit, match="did not return a code: 401"):
        ref.Platform(exposed, None).connect("tamar.gonzaga", "not-the-password")
    with pytest.raises(SystemExit, match="did not return a code: 401"):
        ref.Platform(exposed, None).connect("somebody.else", PASSWORD)


def test_the_token_exchange_requires_the_pkce_verifier(exposed: str) -> None:
    import base64
    import urllib.parse

    ref = _platform()
    p = ref.Platform(exposed, None)
    base = exposed.rsplit("/mcp", 1)[0]
    _, _, client = p.json("POST", f"{base}/register", {"redirect_uris": [ref.REDIRECT]})
    challenge = base64.urlsafe_b64encode(hashlib.sha256(b"right").digest()).rstrip(b"=").decode()
    form = {
        "client_id": client["client_id"],
        "redirect_uri": ref.REDIRECT,
        "response_type": "code",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "username": "tamar.gonzaga",
        "password": PASSWORD,
    }
    status, headers, _ = p.request(
        "POST", f"{base}/authorize", urllib.parse.urlencode(form).encode(),
        {"Content-Type": "application/x-www-form-urlencoded"},
    )  # fmt: skip
    code = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(headers["Location"]).query))["code"]

    def exchange(verifier: str) -> tuple[int, Any]:
        body = urllib.parse.urlencode(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": ref.REDIRECT,
                "client_id": client["client_id"],
                "code_verifier": verifier,
            }
        ).encode()
        status, _, data = p.request(
            "POST", f"{base}/token", body, {"Content-Type": "application/x-www-form-urlencoded"}
        )
        return status, json.loads(data)

    status, answer = exchange("wrong")
    assert status == 400 and answer["error"] == "invalid_grant"
    status, answer = exchange("right")  # the code was spent by the failed attempt
    assert status == 400


def test_nothing_a_platform_sees_names_a_test(exposed: str) -> None:
    ref = _platform()
    p = ref.Platform(exposed, None)
    base = exposed.rsplit("/mcp", 1)[0]
    _, _, client = p.json(
        "POST", f"{base}/register", {"redirect_uris": [ref.REDIRECT], "client_name": "c"}
    )
    seen: list[str] = [json.dumps(client)]
    for path in (
        "/.well-known/oauth-protected-resource",
        "/.well-known/oauth-authorization-server",
    ):
        seen.append(json.dumps(p.json("GET", f"{base}{path}")[2]))
    query = f"response_type=code&client_id={client['client_id']}&redirect_uri={ref.REDIRECT}&code_challenge=x&code_challenge_method=S256"
    status, headers, page = p.request("GET", f"{base}/authorize?{query}")
    assert status == 200 and "Sign in · Rookwood Outfitters" in page.decode()
    seen += [page.decode(), json.dumps(headers)]
    assert [f for text in seen for f in findings(text)] == []


def test_unframe_keeps_only_standard_output() -> None:
    buffer = bytearray(
        struct.pack(">BxxxL", 1, 5)
        + b"hello"
        + struct.pack(">BxxxL", 2, 3)
        + b"err"
        + struct.pack(">BxxxL", 1, 2)
        + b"!"
    )
    assert ingress_relay.unframe(buffer) == [b"hello"]
    assert bytes(buffer) == struct.pack(">BxxxL", 1, 2) + b"!"  # incomplete: kept for later
    buffer.extend(b"?")
    assert ingress_relay.unframe(buffer) == [b"!?"] and not buffer


def test_the_relay_carries_a_connection_byte_for_byte() -> None:
    """A stand-in for the Docker exec stream: it echoes what it is sent, framed as Docker
    frames standard output, until its input closes."""

    def open_stream() -> socket.socket:
        ours, theirs = socket.socketpair()

        def echo() -> None:
            with theirs:
                while data := theirs.recv(4096):
                    theirs.sendall(struct.pack(">BxxxL", 1, len(data)) + data)

        threading.Thread(target=echo, daemon=True).start()
        return ours

    client, relay_end = socket.socketpair()
    threading.Thread(
        target=ingress_relay._carry, args=(relay_end, open_stream), daemon=True
    ).start()  # pyright: ignore[reportPrivateUsage]
    payload = bytes(range(256)) * 40  # every byte value, as binary as it gets
    client.sendall(payload)
    client.shutdown(socket.SHUT_WR)
    got = b""
    client.settimeout(5)
    while chunk := client.recv(65536):
        got += chunk
    assert got == payload


def _manifest(remote: dict[str, str] | None) -> Manifest:
    tools: dict[str, Any] = {
        "id": "tools",
        "kind": "mcp-server",
        "hostname": "mcp.rookwood.com",
        "serves": {"tools_from": {"file": "tools.json"}, "backed_by": ["code"]},
    }
    if remote:
        tools["remote"] = remote
    return Manifest.model_validate(
        {
            "version": 1,
            "name": "w",
            "company": {"name": "Rookwood Outfitters", "domain": "rookwood.com", "seed": 5},
            "apps": [
                {"id": "code", "product": "gitea", "hostname": "git.rookwood.com"},
                tools,
            ],
        }
    )


def test_the_ingress_sits_alone_with_the_exposed_front() -> None:
    plain = sandbox.plan_from(_manifest(None))
    assert not plain.exposed
    blank = sandbox._blank_secrets  # pyright: ignore[reportPrivateUsage]
    assert sandbox.INGRESS_NAME not in [s.name for s in sandbox.specs(plain, [], [], blank(plain))]
    plan = sandbox.plan_from(_manifest({"hostname": "tools.rookwood.com"}))
    assert [a.id for a in plan.exposed] == ["tools"]
    specs = {s.name: s for s in sandbox.specs(plan, [], ["s3cret"], blank(plan))}
    ingress = specs[sandbox.INGRESS_NAME]
    assert ingress.networks == {sandbox.INGRESS: plan.addr.ingress_ip}  # nothing else
    assert "--listen-host" in ingress.command and "127.0.0.1" in ingress.command
    front_spec = specs[plan.exposed[0].container]
    assert set(front_spec.networks) == {sandbox.APPS, sandbox.INGRESS}
    members = [s.name for s in specs.values() if sandbox.INGRESS in s.networks]
    assert sorted(members) == sorted([sandbox.INGRESS_NAME, front_spec.name])
    routes = json.loads(sandbox.ingress_routes(plan, ["s3cret"]))
    assert list(routes["routes"]) == ["tools.rookwood.com"]
    assert routes["routes"]["tools.rookwood.com"]["upstream"].startswith(
        f"http://{plan.exposed[0].ingress_ip}:"
    )
    assert routes["secrets"] == ["s3cret"]


def test_exposure_is_a_restart_and_refuses_what_it_should(tmp_path: Path) -> None:
    from mirrordimensions.service import environment as env
    from mirrordimensions.service import expose as svc
    from mirrordimensions.service import load_project

    root = portal_fixture.make_project(tmp_path)
    project = load_project(root)
    with pytest.raises(MirrorError, match="contains mirror"):
        svc.check_hostname("tools.mirrordimensions.com")
    with pytest.raises(MirrorError, match="not one of this world's MCP servers"):
        svc.expose(project, "code", "tools.elmstead-mutual.com", "scripted-good")
    change = None
    # The fixture world has no MCP server; unexposing something unexposed is refused too.
    with pytest.raises(MirrorError, match="is not exposed"):
        change = svc.unexpose(project, "code")
    assert change is None
    caddy, nginx = svc.proxy_settings("tools.elmstead-mutual.com", 7480)
    assert "reverse_proxy 127.0.0.1:7480" in caddy and "proxy_buffering off" in nginx
    assert env.pending_changes(project) == []


# -- part 2: remote runs ---------------------------------------------------------------------


def test_ingress_events_are_kept_apart_from_the_gateways() -> None:
    from mirrordimensions.network.events import parse_gateway, parse_ingress

    exchange = json.dumps(
        {"source": "gateway", "seq": 5, "type": "http.exchange", "data": {"client": "remote"}}
    )
    message = json.dumps(
        {"source": "gateway", "seq": 6, "type": "mcp.message", "data": {"exchange": 5}}
    )
    gw = parse_gateway(exchange)
    assert gw is not None and gw["data"]["gateway_seq"] == 5 and "via" not in gw["data"]
    ex, msg = parse_ingress(exchange), parse_ingress(message)
    assert ex is not None and msg is not None
    assert ex["data"]["via"] == "ingress" and ex["data"]["gateway_seq"] == "ingress:5"
    assert msg["source"] == "mcp" and msg["data"]["exchange"] == "ingress:5"


def test_a_remote_run_reports_what_it_covers_and_its_two_outside_channels_alone_pass() -> None:
    from mirrordimensions.runner import coverage

    chans = {
        "http": {"status": "captured", "where": "ingress"},
        "model": {"status": "not_captured", "reason": "agent runs outside the world"},
        "agent_host": {"status": "not_captured", "reason": "agent runs outside the world"},
        "state": {"status": "captured", "where": "dumps"},
    }
    ok = coverage.summarize(chans, {"r": {"passed": True}}, outside={"model", "agent_host"})
    assert ok["status"] == "complete" and "only what the agent did to the world" in ok["covers"]
    # Any other channel not captured, or a failed reconciliation, still makes it incomplete.
    gap = {**chans, "mcp": {"status": "not_captured", "reason": "x"}}
    assert coverage.summarize(gap, {}, outside={"model", "agent_host"})["status"] == "incomplete"
    bad = coverage.summarize(chans, {"r": {"passed": False}}, outside={"model", "agent_host"})
    assert bad["status"] == "incomplete"
    # A hosted run gets no such exemption.
    assert coverage.summarize(chans, {})["status"] == "incomplete"


def test_the_mcp_reconciliation_ignores_sign_in_on_an_exposed_server() -> None:
    from mirrordimensions.mcp.world import reconcile

    def ex(seq: str, path: str) -> dict[str, Any]:
        data = {"gateway_seq": seq, "host": "tools.rookwood.com", "method": "POST", "path": path}
        return {"type": "http.exchange", "data": data}

    events = [
        ex("ingress:1", "/token"),
        ex("ingress:2", "/mcp"),
        {"type": "mcp.message", "data": {"exchange": "ingress:2"}},
    ]
    assert reconcile.reconcile(events, {"tools.rookwood.com"}, set(), {"/mcp"}) == []
    assert reconcile.reconcile(events, {"tools.rookwood.com"}, set()) != []


def test_remote_agents_are_the_ingress_client_and_canaries_through_it_left_the_world() -> None:
    from mirrordimensions.config.agent import Agent
    from mirrordimensions.service import runs

    plan = sandbox.plan_from(_manifest({"hostname": "tools.rookwood.com"}))
    agent = Agent.model_validate(
        {
            "name": "helper",
            "mode": "remote",
            "acts_as": {"role": "engineer"},
            "reduced_guarantees": "accepted",
            "grants": {"tools": {}},
        }
    )
    assert runs.agent_clients(plan, agent, servers=False) == {sandbox.REMOTE_CLIENT}
    assert runs.agent_clients(plan, agent) == {sandbox.REMOTE_CLIENT, plan.exposed[0].ip}
    outside = runs._outside  # pyright: ignore[reportPrivateUsage]
    assert outside("event 9: from outside the world: POST tools.rookwood.com/mcp")
    assert outside("event 9: sent out of the world: POST tools.rookwood.com/mcp")
    assert not outside("event 9: POST chat.rookwood.com/api/v4/posts")


def test_the_report_says_what_a_remote_result_covers_on_its_first_screen(tmp_path: Path) -> None:
    from mirrordimensions.runner.coverage import COVERS_REMOTE
    from mirrordimensions.trace import report

    result = {
        "status": "passed",
        "isolation": "remote",
        "scenario": "rotate-leaked-token-mcp",
        "coverage": {"status": "complete", "covers": COVERS_REMOTE},
        "canaries": [{"canary": "canary.token", "seen": ["event 3: x"], "left_world": True}],
    }
    (tmp_path / "result.json").write_text(json.dumps(result), encoding="utf-8")
    (tmp_path / "events.jsonl").write_text("", encoding="utf-8")
    page = report.render(tmp_path)
    notice = page.index("What this covers")
    assert notice < page.index('id="checks"')  # before any section
    assert "left the world</b>" in page
