# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""M7: the operator MCP server (decision 0009), driven by a real MCP client: in process,
over stdio as an AI tool would launch it, and over HTTP with its token."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import anyio
import pytest
from mcp import Client
from mcp.client.stdio import StdioServerParameters

from mirrordimensions.mcp.operator.server import UNTRUSTED, build_server
from mirrordimensions.service import load_project

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import portal_fixture

READ = {
    "status",
    "plan",
    "doctor_report",
    "list_systems",
    "show_system",
    "list_scenarios",
    "list_agents",
    "list_runs",
    "get_result",
    "coverage",
    "ledger",
    "read_steps",
    "search_timeline",
    "agent_reach",
    "pending_changes",
}
ACT_OR_EDIT = {
    "start_run",
    "stop_run",
    "restore_snapshot",
    "run_doctor",
    "set_visibility",
    "set_grant",
    "set_rule",
    "remove_rule",
    "apply_changes",
    "create_world",
}


MIRROR = ["-c", "from mirrordimensions.cli.app import main; main()"]  # the `mirror` command


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return portal_fixture.make_project(tmp_path)


def _with_client(root: Path, body: Any) -> Any:
    async def go() -> Any:
        async with Client(build_server(load_project(root))) as client:
            return await body(client)

    return anyio.run(go)


def _data(result: Any) -> Any:
    assert not result.is_error, result.content
    data = result.structured_content
    return data.get("result", data) if isinstance(data, dict) and list(data) == ["result"] else data


def test_it_offers_the_read_act_and_edit_tools_and_nothing_destructive(root: Path) -> None:
    async def body(client: Client) -> Any:
        return await client.list_tools()

    tools = {t.name: t for t in _with_client(root, body).tools}
    assert set(tools) == READ | ACT_OR_EDIT
    for name in ACT_OR_EDIT:
        assert "confirm" in tools[name].input_schema["properties"], name
    for word in ("destroy", "purge", "delete", "rm"):
        assert not any(word in name for name in tools)


def test_reading_a_world_and_its_runs(root: Path) -> None:
    async def body(client: Client) -> dict[str, Any]:
        return {
            "status": _data(await client.call_tool("status", {})),
            "runs": _data(await client.call_tool("list_runs", {})),
            "result": _data(
                await client.call_tool("get_result", {"run_id": portal_fixture.FINISHED})
            ),
            "raw": _data(
                await client.call_tool(
                    "get_result", {"run_id": portal_fixture.FINISHED, "include_text": True}
                )
            ),
            "steps": _data(
                await client.call_tool("read_steps", {"run_id": portal_fixture.FINISHED})
            ),
            "found": _data(
                await client.call_tool(
                    "search_timeline",
                    {"run_id": portal_fixture.FINISHED, "source": "egress", "limit": 5},
                )
            ),
            "systems": _data(await client.call_tool("list_systems", {})),
        }

    got = _with_client(root, body)
    assert got["status"]["world"] == "northfield-ops" and got["status"]["state"] == "built"
    assert [r["run_id"] for r in got["runs"]][:2] == [portal_fixture.LIVE, portal_fixture.FINISHED]
    facts = got["result"]
    assert facts["status"] == "failed" and "run_content" not in facts
    assert {
        "check": "mattermost.message_contains",
        "kind": "forbidden",
        "passed": False,
        "event": 7,
    } in facts["checks"]
    # Text the agent wrote only arrives on request, fenced off and marked untrusted.
    raw = got["raw"]
    assert raw["untrusted"] == UNTRUSTED
    assert "1 new message(s) contain the text" in json.dumps(raw["run_content"])
    assert got["steps"]["untrusted"] == UNTRUSTED and got["steps"]["by_kind"]["violation"] == 1
    assert [e["seq"] for e in got["found"]["run_content"]] == [6]
    assert {s["id"] for s in got["systems"]} >= {"code", "chat"}


def test_acting_and_editing_need_confirmation_and_are_logged(root: Path) -> None:
    async def body(client: Client) -> dict[str, Any]:
        refused = await client.call_tool("set_visibility", {"system": "chat", "state": "denied"})
        done = await client.call_tool(
            "set_visibility", {"system": "chat", "state": "denied", "confirm": True}
        )
        pending = await client.call_tool("pending_changes", {})
        bad = await client.call_tool(
            "set_grant",
            {"agent": "scripted-good", "resource": "code/nope", "grant": "read", "confirm": True},
        )
        return {"refused": refused, "done": done, "pending": pending, "bad": bad}

    got = _with_client(root, body)
    assert got["refused"].is_error and "confirm=true" in got["refused"].content[0].text
    assert _data(got["done"])["applies"] == "next run"
    assert "visibility: denied" in (root / "mirror.yaml").read_text("utf-8")
    assert [c["what"] for c in _data(got["pending"])] == ["Team chat: visibility granted to denied"]
    # A service error comes back as an actionable tool error, not a crash.
    assert got["bad"].is_error and "has no repo called 'nope'" in got["bad"].content[0].text
    logged = [
        json.loads(line)
        for line in (root / ".mirror" / "operator.log").read_text("utf-8").splitlines()
    ]
    assert [entry["tool"] for entry in logged] == ["set_visibility"]


def test_a_long_operation_reports_its_progress(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from mirrordimensions.service import world as world_svc
    from mirrordimensions.service import worlddef

    def fake(_project: Any, resume: bool = True, on_stage: Any = None, **_: Any) -> int:
        for number, stage in enumerate(worlddef.STAGES, start=1):
            on_stage(f"{number}. {stage}")
        return len(worlddef.STAGES)

    monkeypatch.setattr(world_svc, "create_world", fake)
    seen: list[tuple[float, str | None]] = []

    async def progress(value: float, total: float | None, message: str | None) -> None:
        seen.append((value, message))

    async def body(client: Client) -> Any:
        return await client.call_tool("create_world", {"confirm": True}, progress_callback=progress)

    result = _data(_with_client(root, body))
    assert result["last_stage"] == 8
    assert [m for _, m in seen][-1] == "8. Ready" and len(seen) == 8


def test_over_stdio_as_an_ai_tool_launches_it(root: Path) -> None:
    """`mirror mcp serve` keeps stdout for the protocol: nothing else may be printed there."""
    params = StdioServerParameters(
        command=sys.executable,
        args=[*MIRROR, "--project", str(root), "mcp", "serve"],
        env={**os.environ},
    )

    async def go() -> Any:
        async with Client(params) as client:
            return _data(await client.call_tool("status", {}))

    assert anyio.run(go)["world"] == "northfield-ops"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def test_over_http_only_with_the_token_and_only_by_this_computers_names(root: Path) -> None:
    import httpx

    port = _free_port()
    server = subprocess.Popen(
        [
            sys.executable,
            *MIRROR,
            "--project",
            str(root),
            "mcp",
            "serve",
            "--http",
            "--port",
            str(port),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )
    try:
        token = ""
        deadline = time.time() + 30
        assert server.stdout is not None
        while time.time() < deadline and not token:
            line = server.stdout.readline()
            if "Bearer" in line:
                token = line.split("Bearer", 1)[1].strip()
        assert token
        url = f"http://127.0.0.1:{port}/mcp"
        hello = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "t", "version": "1"},
            },
        }
        accept = {"Accept": "application/json, text/event-stream"}
        for _ in range(50):
            try:
                refused = httpx.post(url, json=hello, headers=accept, timeout=5)
                break
            except httpx.ConnectError:
                time.sleep(0.2)
        assert refused.status_code == 401
        rebound = httpx.post(
            url,
            json=hello,
            headers={
                **accept,
                "Authorization": f"Bearer {token}",
                "Host": f"attacker.example:{port}",
            },
            timeout=5,
        )
        assert rebound.status_code in (403, 421)
        ok = httpx.post(
            url, json=hello, headers={**accept, "Authorization": f"Bearer {token}"}, timeout=5
        )
        assert ok.status_code == 200 and "mirrordimensions-operator" in ok.text
        marker = json.loads((root / ".mirror" / "operator.json").read_text("utf-8"))
        assert marker["port"] == port  # for `mirror doctor` to probe from the sandbox
    finally:
        server.terminate()
        server.wait(timeout=10)


def test_a_marker_left_by_a_stopped_server_is_not_trusted(root: Path) -> None:
    from mirrordimensions.service.sandbox import running_operator_port, running_portal_port

    project = load_project(root)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = int(listener.getsockname()[1])
        for name in ("operator.json", "portal.json"):
            (root / ".mirror" / name).write_text(json.dumps({"port": port}), encoding="utf-8")
        assert running_operator_port(project) == port
        assert running_portal_port(project) == port
    # Nothing listens now: doctor probes a stand-in on the default port instead.
    assert running_operator_port(project) is None
    assert running_portal_port(project) is None
