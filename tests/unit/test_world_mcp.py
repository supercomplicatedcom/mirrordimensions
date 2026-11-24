# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""The world MCP server (decision 0009): the front, its tool set, and capture at the gateway."""

from __future__ import annotations

import json
import ssl
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, ClassVar

import pytest

from mirrordimensions.errors import MirrorError
from mirrordimensions.mcp.world import front, toolset
from mirrordimensions.network.payloads import mcpcap
from mirrordimensions.world.denylist import findings

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "mcp" / "eng-tools"
SERVES = {"tools_from": {"file": "tools.json"}, "surfaces": "surfaces.yaml"}
TOKEN = "0f3a" * 10


# Requests go to local test servers only (http://127.0.0.1).
# ruff: noqa: S310

# -- a stand-in for the twins' APIs --------------------------------------------------------


class Backend(BaseHTTPRequestHandler):
    seen: ClassVar[list[tuple[str, str, str, bytes]]] = []

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _reply(self, status: int, body: Any) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _record(self) -> bytes:
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        Backend.seen.append((self.command, self.path, self.headers.get("Authorization", ""), body))
        return body

    def do_GET(self) -> None:
        self._record()
        if self.path.startswith("/api/v1/repos/issues/search"):
            return self._reply(
                200,
                [{"number": 3, "title": "Rounding", "repository": {"full_name": "acme/billing"}}],
            )
        if self.path == "/api/v4/users/me/teams":
            return self._reply(200, [{"id": "team1", "name": "acme"}])
        if self.path == "/api/v4/teams/team1/channels/name/platform-team":
            return self._reply(200, {"id": "chan9", "name": "platform-team"})
        self._reply(404, {"message": "The target couldn't be found."})

    def do_POST(self) -> None:
        body = self._record()
        if "/platform-docs/" in self.path:
            return self._reply(
                403, {"message": "user does not have permission to write to this repository"}
            )
        self._reply(201, {"id": 77, "body": json.loads(body or b"{}").get("body")})


def serve(handler: type[BaseHTTPRequestHandler]) -> tuple[ThreadingHTTPServer, str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


@pytest.fixture
def tools() -> toolset.Toolset:
    return toolset.load(EXAMPLE, "tools", SERVES, {"code", "chat", "tools"})


@pytest.fixture
def mcp(tools: toolset.Toolset, tmp_path: Path) -> Iterator[str]:
    Backend.seen = []
    backend, base = serve(Backend)
    config = toolset.front_config(tools, {"code": "git.acme.com", "chat": "chat.acme.com"})
    for app in config["backends"].values():
        app["base"] = base
    config["tokens"] = {
        TOKEN: {"person": "ana.silva", "backends": {"code": "gt", "chat": "mt"}, "tools": None}
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    front.Handler.config = front.Config(str(path))
    front.Handler.sessions = {}
    front.Handler.context = ssl.create_default_context()
    server, url = serve(front.Handler)
    yield url + "/mcp"
    server.shutdown()
    backend.shutdown()


def post(
    url: str,
    body: dict[str, Any],
    headers: dict[str, str] | None = None,
    token: str | None = TOKEN,
) -> tuple[int, dict[str, str], Any]:
    base = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    if token:
        base["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        url, json.dumps(body).encode(), {**base, **(headers or {})}, method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            raw = response.read()
            return response.status, dict(response.headers), json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        return exc.code, dict(exc.headers), json.loads(raw) if raw else None


META = {
    "io.modelcontextprotocol/protocolVersion": "2026-07-28",
    "io.modelcontextprotocol/clientInfo": {"name": "assistant", "version": "1.0"},
    "io.modelcontextprotocol/clientCapabilities": {},
}


def modern(
    url: str, method: str, params: dict[str, Any] | None = None, **headers: str
) -> tuple[int, dict[str, str], Any]:
    params = {**(params or {}), "_meta": META}
    sent = {"MCP-Protocol-Version": "2026-07-28", "Mcp-Method": method}
    if "name" in params:
        sent["Mcp-Name"] = params["name"]
    sent.update(headers)
    return post(url, {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, sent)


# -- modern clients ---------------------------------------------------------------------------


def test_discover_and_list_report_the_production_server(mcp: str) -> None:
    status, headers, reply = modern(mcp, "server/discover")
    assert status == 200 and headers["Server"] == "uvicorn"
    result = reply["result"]
    assert result["resultType"] == "complete"
    assert result["supportedVersions"] == ["2026-07-28", "2025-11-25", "2025-06-18"]
    assert result["_meta"]["io.modelcontextprotocol/serverInfo"] == {
        "name": "eng-tools",
        "version": "2.3.1",
    }
    _, _, listed = modern(mcp, "tools/list")
    exported = json.loads((EXAMPLE / "tools.json").read_text(encoding="utf-8"))["tools"]
    assert listed["result"]["tools"] == exported  # verbatim


def test_scripted_goods_work_through_tools(mcp: str) -> None:
    _, _, found = modern(mcp, "tools/call", {"name": "search_issues", "arguments": {}})
    issues = json.loads(found["result"]["content"][0]["text"])
    assert issues[0]["number"] == 3 and found["result"]["isError"] is False
    args = {"owner": "acme", "repo": "billing", "number": 3, "body": "On it."}
    _, _, commented = modern(mcp, "tools/call", {"name": "add_issue_comment", "arguments": args})
    assert commented["result"]["isError"] is False
    _, _, posted = modern(
        mcp,
        "tools/call",
        {"name": "post_message", "arguments": {"channel": "platform-team", "message": "Hi"}},
    )
    assert posted["result"]["isError"] is False
    calls = [(m, p, a) for m, p, a, _ in Backend.seen]
    assert ("POST", "/api/v1/repos/acme/billing/issues/3/comments", "token gt") in calls
    assert ("POST", "/api/v4/posts", "Bearer mt") in calls
    assert json.loads(Backend.seen[-1][3]) == {"channel_id": "chan9", "message": "Hi"}
    assert "state=open" in Backend.seen[0][1] and "assigned=true" in Backend.seen[0][1]


def test_an_out_of_grant_call_gets_the_backends_own_error(mcp: str) -> None:
    args = {"owner": "acme", "repo": "platform-docs", "number": 1, "body": "x"}
    status, _, reply = modern(mcp, "tools/call", {"name": "add_issue_comment", "arguments": args})
    assert status == 200 and reply["result"]["isError"] is True
    assert "user does not have permission" in reply["result"]["content"][0]["text"]


def test_protocol_errors(mcp: str) -> None:
    status, _, reply = modern(mcp, "tools/call", {"name": "drop_tables", "arguments": {}})
    assert reply["error"] == {"code": -32602, "message": "Unknown tool: drop_tables"}
    status, _, reply = modern(mcp, "resources/list")
    assert status == 404 and reply["error"]["code"] == -32601
    status, _, reply = modern(mcp, "tools/list", **{"Mcp-Method": "tools/call"})
    assert status == 400 and reply["error"]["code"] == -32020
    status, _, reply = modern(
        mcp, "tools/call", {"name": "get_issue", "arguments": {}}, **{"Mcp-Name": "other"}
    )
    assert status == 400 and reply["error"]["code"] == -32020
    status, _, reply = modern(mcp, "tools/list", **{"MCP-Protocol-Version": "2025-11-25"})
    assert status == 400 and reply["error"]["code"] == -32020
    old = {**META, "io.modelcontextprotocol/protocolVersion": "2027-01-01"}
    status, _, reply = post(
        mcp,
        {"jsonrpc": "2.0", "id": 5, "method": "tools/list", "params": {"_meta": old}},
        {"MCP-Protocol-Version": "2027-01-01", "Mcp-Method": "tools/list"},
    )
    assert status == 400 and reply["error"]["code"] == -32022
    assert reply["error"]["data"]["requested"] == "2027-01-01"


def test_base64_tool_names_in_headers_are_decoded(mcp: str) -> None:
    status, _, reply = modern(
        mcp,
        "tools/call",
        {"name": "search_issues", "arguments": {}},
        **{"Mcp-Name": "=?base64?c2VhcmNoX2lzc3Vlcw==?="},
    )
    assert status == 200 and reply["result"]["isError"] is False


def test_a_notification_is_accepted_without_a_body(mcp: str) -> None:
    status, _, reply = post(
        mcp,
        {"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"_meta": META}},
        {"MCP-Protocol-Version": "2026-07-28", "Mcp-Method": "notifications/cancelled"},
    )
    assert status == 202 and reply is None


def test_authentication_and_origin(mcp: str) -> None:
    status, headers, reply = modern_without_token(mcp)
    assert status == 401 and headers["WWW-Authenticate"].startswith("Bearer")
    assert reply["error"] == "invalid_token"
    status, _, _ = modern(mcp, "tools/list", Origin="https://evil.example.net")
    assert status == 403
    with pytest.raises(urllib.error.HTTPError) as info:
        urllib.request.urlopen(mcp, timeout=5)
    assert info.value.code == 405


def modern_without_token(url: str) -> tuple[int, dict[str, str], Any]:
    return post(
        url,
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {"_meta": META}},
        {"MCP-Protocol-Version": "2026-07-28", "Mcp-Method": "tools/list"},
        token=None,
    )


# -- legacy clients -----------------------------------------------------------------------


def test_a_legacy_client_initializes_and_keeps_a_session(mcp: str) -> None:
    init = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "assistant", "version": "1.0"},
        },
    }
    status, headers, reply = post(mcp, init)
    assert status == 200 and reply["result"]["protocolVersion"] == "2025-06-18"
    assert reply["result"]["serverInfo"]["name"] == "eng-tools"
    assert "resultType" not in reply["result"]
    session = headers["Mcp-Session-Id"]
    with_session = {"Mcp-Session-Id": session, "MCP-Protocol-Version": "2025-06-18"}
    status, _, _ = post(
        mcp, {"jsonrpc": "2.0", "method": "notifications/initialized"}, with_session
    )
    assert status == 202
    _, _, listed = post(mcp, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, with_session)
    assert len(listed["result"]["tools"]) == 4
    status, _, reply = post(mcp, {"jsonrpc": "2.0", "id": 3, "method": "tools/list"})
    assert status == 400
    status, _, _ = post(
        mcp, {"jsonrpc": "2.0", "id": 4, "method": "tools/list"}, {"Mcp-Session-Id": "nope"}
    )
    assert status == 404


def test_an_unknown_legacy_version_gets_the_newest_legacy_one(mcp: str) -> None:
    init = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {"protocolVersion": "2024-11-05"},
    }
    _, _, reply = post(mcp, init)
    assert reply["result"]["protocolVersion"] == "2025-11-25"


def test_grants_limit_the_tools_a_token_sees(mcp: str, tmp_path: Path) -> None:
    config = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
    config["tokens"][TOKEN]["tools"] = ["search_issues", "get_issue"]
    (tmp_path / "config.json").write_text(json.dumps(config), encoding="utf-8")
    front.Handler.config.mtime = -1  # the file changed within the same second
    _, _, listed = modern(mcp, "tools/list")
    assert [t["name"] for t in listed["result"]["tools"]] == ["search_issues", "get_issue"]
    _, _, reply = modern(mcp, "tools/call", {"name": "post_message", "arguments": {}})
    assert reply["error"]["code"] == -32602


# -- the tool set -------------------------------------------------------------------------


def test_the_example_tool_set_is_valid_and_names_nothing(tools: toolset.Toolset) -> None:
    assert tools.names == ["search_issues", "get_issue", "add_issue_comment", "post_message"]
    visible = json.dumps(
        {"server": tools.server, "instructions": tools.instructions, "tools": tools.tools}
    )
    assert not findings(visible)
    config = toolset.front_config(tools, {"code": "git.acme.com", "chat": "chat.acme.com"})
    assert set(config) == {
        "endpoint",
        "server",
        "versions",
        "instructions",
        "tools",
        "routes",
        "backends",
        "tokens",
    }  # tool definitions and routes only: no world, scenario, check or canary
    assert config["backends"]["code"] == {"base": "https://git.acme.com", "auth": "token"}


def test_every_message_the_front_writes_names_nothing() -> None:
    source = (Path(front.__file__)).read_text(encoding="utf-8")
    import re

    literals = " ".join(re.findall(r'"([^"\n]{3,})"', source))
    sent = [x for x in literals.split(" ") if x]
    assert not findings(" ".join(s for s in sent if not s.startswith(("/etc/", "TOOLS_"))))


def test_tool_set_problems_name_their_fix(tmp_path: Path) -> None:
    (tmp_path / "tools.json").write_text(
        json.dumps({"serverInfo": {"name": "x", "version": "1"}, "tools": [{"name": "a"}]}),
        encoding="utf-8",
    )
    (tmp_path / "surfaces.yaml").write_text(
        "backends: {code: {auth: token}}\ntools: {}\n", encoding="utf-8"
    )
    with pytest.raises(MirrorError, match="has no surface"):
        toolset.load(tmp_path, "t", SERVES, {"code"})
    with pytest.raises(MirrorError, match="not available yet"):
        toolset.load(tmp_path, "t", {"tools_from": {"catalog": "x"}}, {"code"})
    with pytest.raises(MirrorError, match="does not exist"):
        toolset.load(tmp_path, "t", {"tools_from": {"file": "no.json"}, "surfaces": "s"}, set())
    (tmp_path / "surfaces.yaml").write_text(
        "backends: {code: {auth: token}}\ntools:\n  a: {access: read, steps: "
        "[{app: code, method: GET, path: '/x/{$0.id}'}]}\n",
        encoding="utf-8",
    )
    with pytest.raises(MirrorError, match="refers to a later step"):
        toolset.load(tmp_path, "t", SERVES, {"code"})


# -- capture at the gateway ------------------------------------------------------------------


def test_each_message_and_call_becomes_an_event(tools: toolset.Toolset) -> None:
    request = {
        "jsonrpc": "2.0",
        "id": 7,
        "method": "tools/call",
        "params": {
            "name": "add_issue_comment",
            "arguments": {"owner": "acme", "repo": "billing", "number": 3, "body": "key sk-123"},
            "_meta": META,
        },
    }
    reply = {
        "jsonrpc": "2.0",
        "id": 7,
        "result": {
            "resultType": "complete",
            "content": [{"type": "text", "text": "{}"}],
            "isError": False,
        },
    }
    found = mcpcap.events(
        json.dumps(request).encode(),
        "application/json",
        json.dumps(reply).encode(),
        "application/json",
        toolset.gateway_surfaces(tools),
        ["sk-123"],
    )
    kinds = [k for k, _ in found]
    assert kinds == ["mcp.message", "mcp.message", "mcp.call"]
    sent, received, call = (d for _, d in found)
    assert sent["direction"] == "client" and sent["version"] == "2026-07-28"
    assert received["kind"] == "response"
    assert call["tool"] == "add_issue_comment" and call["access"] == "write"
    assert call["resource"] == "issue:acme/billing#3"
    assert call["sentence"] == "Comments on issue #3 in billing"
    assert "sk-123" not in json.dumps(found) and call["is_error"] is False


def test_streamed_replies_and_errors_are_parsed() -> None:
    sse = (
        b'event: message\ndata: {"jsonrpc":"2.0","method":"notifications/progress","params":{}}\n\n'
        b'data: {"jsonrpc":"2.0","id":1,"error":{"code":-32602,"message":"Unknown tool: z"}}\n\n'
    )
    request = json.dumps(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "z"}}
    ).encode()
    found = mcpcap.events(request, "application/json", sse, "text/event-stream", {}, [])
    kinds = [(k, d.get("kind")) for k, d in found]
    assert kinds == [
        ("mcp.message", "request"),
        ("mcp.message", "notification"),
        ("mcp.message", "error"),
        ("mcp.call", None),
    ]
    call = found[-1][1]
    assert call["known"] is False and call["is_error"] is True and call["error_code"] == -32602


# -- reconciliation ------------------------------------------------------------------------


def _event(seq: int, kind: str, **data: Any) -> dict[str, Any]:
    return {"source": "gateway", "type": kind, "data": {"gateway_seq": seq, **data}}


def test_the_mcp_channel_reconciles_with_the_servers_own_writes() -> None:
    from mirrordimensions.mcp.world.reconcile import reconcile

    agent, server, host = "10.40.0.121", "10.41.0.23", "mcp.acme.com"
    events = [
        _event(1, "http.exchange", host=host, method="POST", client=agent),
        _event(2, "mcp.message", exchange=1, client=agent),
        _event(3, "http.exchange", host="git.acme.com", method="POST", client=server),
        _event(4, "http.exchange", host=host, method="POST", client=agent),
        _event(5, "mcp.message", exchange=4, client=agent),
        _event(
            6,
            "mcp.call",
            exchange=4,
            client=agent,
            tool="add_issue_comment",
            access="write",
            is_error=False,
        ),
        _event(7, "http.exchange", host=host, method="POST", client=agent),
        _event(8, "mcp.message", exchange=7, client=agent),
        _event(
            9, "mcp.call", exchange=7, client=agent, tool="get_issue", access="read", is_error=False
        ),
    ]
    assert reconcile(events, {host}, {server}) == []
    no_write = [e for e in events if e["data"]["gateway_seq"] != 3]
    assert reconcile(no_write, {host}, {server}) == [
        "add_issue_comment succeeded but no write reached a system"
    ]
    no_message = [e for e in events if e["data"]["gateway_seq"] != 8]
    assert reconcile(no_message, {host}, {server}) == [
        "exchange 7 with mcp.acme.com has no mcp.message"
    ]
