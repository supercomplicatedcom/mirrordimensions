# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""M7: a run's events grouped into the live view's steps, and `mirror watch`."""

from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from mirrordimensions.cli.app import app
from mirrordimensions.service import load_project, runlog
from mirrordimensions.trace import steps
from mirrordimensions.twins.profile import profile_of
from mirrordimensions.world import naming
from mirrordimensions.world.model import World

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import portal_fixture

AGENT_IP = "10.40.0.5"
CODE = steps.System("code", "Code hosting", profile_of("gitea").table)
CHAT = steps.System("chat", "Team chat", profile_of("mattermost").table)
CTX = steps.Context(
    agent="ops",
    clients={AGENT_IP},
    systems={"git.example.test": CODE, "chat.example.test": CHAT},
    model_hosts={"api.anthropic.com"},
)


def ev(seq: int, second: float, kind: str, /, **data: Any) -> dict[str, Any]:
    source = {
        "run.start": "runner",
        "work.delivered": "runner",
        "run.end": "runner",
        "http.exchange": "gateway",
        "mcp.call": "gateway",
        "model.exchange": "model",
        "model.refused": "model",
        "dns.query": "dns",
        "egress.blocked": "egress",
        "check.result": "evaluator",
        "side_effect.unexpected": "evaluator",
    }[kind]
    ts = f"2026-11-24T10:00:{int(second):02d}.{round((second % 1) * 1000):03d}Z"
    return {"seq": seq, "ts": ts, "source": source, "type": kind, "data": data}


def http(seq: int, second: float, method: str, path: str, status: int = 200, **more: Any):
    return ev(
        seq,
        second,
        "http.exchange",
        method=method,
        host="git.example.test",
        path=path,
        status=status,
        client=AGENT_IP,
        **more,
    )


FILE = "/api/v1/repos/elmstead/billing-service/contents/config/settings.py"


def test_requests_to_one_resource_within_two_seconds_are_one_step() -> None:
    found = steps.steps_of(
        [
            ev(1, 0, "run.start"),
            http(2, 1.0, "GET", FILE),
            http(3, 1.5, "GET", FILE + "?ref=main"),
            http(4, 4.0, "GET", FILE),  # more than two seconds later: a step of its own
        ],
        CTX,
    )
    assert [(s.sentence, s.events, s.requests) for s in found] == [
        ("Reads config/settings.py", [2, 3], 2),
        ("Reads config/settings.py", [4], 1),
    ]
    first = found[0]
    assert first.location.label == "Code hosting, billing-service"
    assert first.location.place == "repo:elmstead/billing-service"
    assert first.location.resource == "file:elmstead/billing-service/config/settings.py"
    assert first.at == "00:01.0" and first.detail.endswith("(and 1 more)")


def test_a_change_is_never_hidden_inside_the_reads_before_it() -> None:
    found = steps.steps_of(
        [http(1, 0, "GET", FILE), http(2, 0.2, "PUT", FILE), http(3, 0.4, "PUT", FILE)], CTX
    )
    assert [(s.sentence, s.events) for s in found] == [
        ("Reads config/settings.py", [1]),
        ("Commits a change to config/settings.py", [2, 3]),
    ]


def test_each_kind_of_step() -> None:
    found = steps.steps_of(
        [
            ev(1, 0, "run.start"),
            ev(2, 1, "work.delivered", channel="gitea.issue_assigned", **{"from": "a.lead"}),
            ev(
                3, 2, "model.exchange", model="m", input_tokens=10, output_tokens=5, duration_ms=900
            ),
            http(4, 3, "GET", "/api/v1/repos/elmstead/payroll-exports/contents/q3.csv", 403),
            ev(5, 4, "dns.query", name="pastebin.com.", rcode="NXDOMAIN", client=AGENT_IP),
            ev(6, 4.5, "dns.query", name="pastebin.com.", rcode="NXDOMAIN", client=AGENT_IP),
            ev(7, 5, "egress.blocked", src=AGENT_IP, dst="1.1.1.1", dport=443, proto="TCP"),
            ev(8, 5.2, "dns.query", name="git.example.test", rcode="NOERROR", client=AGENT_IP),
            ev(9, 6, "model.refused", reason="hosted tool"),
            ev(10, 7, "run.end", status="failed"),
        ],
        CTX,
    )
    assert [(s.kind, s.location.system, s.sentence) for s in found] == [
        ("info", "agent", "Work arrives"),
        ("think", "model", "Thinks"),
        ("blocked", "code", "Reads q3.csv (refused)"),
        ("blocked", "outside", "Looks up pastebin.com"),
        ("blocked", "outside", "Tries to connect to 1.1.1.1:443"),
        ("blocked", "model", "A model call is refused"),
        ("end", "agent", "Run ended: failed"),
    ]
    assert found[0].detail == "issue assigned from a.lead"
    assert found[1].detail == "m, 10 in / 5 out, 0.9 s"
    assert found[3].events == [5, 6]  # the same failed lookup, twice, is one step
    assert found[2].location.label == "Code hosting, payroll-exports"


def test_other_clients_and_the_model_hosts_own_exchanges_are_not_steps() -> None:
    others = http(1, 0, "GET", FILE) | {
        "data": {**http(1, 0, "GET", FILE)["data"], "client": "10.40.0.9"}
    }
    model = ev(
        2,
        1,
        "http.exchange",
        host="api.anthropic.com",
        method="POST",
        path="/v1/messages",
        status=200,
        client=AGENT_IP,
    )
    assert steps.steps_of([others, model], CTX) == []


def test_a_broken_forbidden_check_marks_the_step_that_broke_it() -> None:
    events = [
        http(1, 0, "GET", FILE),
        http(2, 1, "PUT", FILE),
        ev(
            3,
            9,
            "check.result",
            check="gitea.file_contains",
            kind="forbidden",
            passed=False,
            evidence="the token is still there",
            event=2,
        ),
        ev(4, 9, "check.result", check="ok", kind="success", passed=True),
        ev(
            5,
            9.1,
            "check.result",
            check="mattermost.message_contains",
            kind="forbidden",
            passed=False,
            evidence="posted",
        ),
    ]
    found = steps.steps_of(events, CTX)
    assert [s.kind for s in found] == ["request", "violation", "violation"]
    assert found[1].events == [2, 3] and "the token is still there" in found[1].detail
    assert found[2].sentence == "Breaks mattermost.message_contains"


def test_following_sends_a_step_again_when_it_changes() -> None:
    events = [
        http(1, 0, "GET", FILE),
        http(2, 0.5, "GET", FILE),
        ev(3, 9, "check.result", check="c", kind="forbidden", passed=False, evidence="e", event=1),
    ]
    seen = [(s.index, len(s.events), s.kind) for s in steps.follow_steps(events, CTX)]
    assert seen == [(0, 1, "request"), (0, 2, "request"), (0, 3, "violation")]


def test_a_page_and_what_it_loads_by_itself_are_one_step() -> None:
    found = steps.steps_of(
        [
            http(1, 0, "GET", "/elmstead/billing-service/issues/14"),
            http(2, 0.1, "GET", "/assets/css/index.css"),
            http(3, 0.2, "GET", "/avatars/0a1b"),
            http(4, 0.3, "GET", "/-/ws"),
        ],
        CTX,
    )
    assert [(s.sentence, s.events) for s in found] == [
        ("Opens issue #14 in billing-service", [1, 2, 3, 4])
    ]


def test_tool_calls_through_an_mcp_server_are_steps_at_that_server() -> None:
    ctx = steps.Context(
        agent="ops",
        clients={AGENT_IP},
        systems={"mcp.example.test": steps.System("mcp", "Tools", None, mcp=True)},
    )
    found = steps.steps_of(
        [
            ev(
                1,
                0,
                "http.exchange",
                host="mcp.example.test",
                method="POST",
                path="/mcp",
                status=200,
                client=AGENT_IP,
            ),
            ev(
                2,
                0,
                "mcp.call",
                host="mcp.example.test",
                client=AGENT_IP,
                tool="search_issues",
                sentence="Searches the issues assigned to it",
                resource=None,
                is_error=False,
            ),
        ],
        ctx,
    )
    assert [(s.kind, s.location.label, s.sentence, s.requests) for s in found] == [
        ("request", "Tools", "Searches the issues assigned to it", 1)
    ]


def test_an_older_run_is_located_from_its_stored_bodies() -> None:
    bodies = {
        "bodies/1.resp": json.dumps({"id": "k3j4h5k3j4h5k3j4h5k3j4h5k3", "name": "incidents"}),
        "bodies/2.req": json.dumps({"channel_id": "k3j4h5k3j4h5k3j4h5k3j4h5k3", "message": "x"}),
    }
    ctx = steps.Context(
        agent="ops",
        clients={AGENT_IP},
        systems={"chat.example.test": CHAT},
        body=lambda ref: bodies.get(ref, "").encode(),
    )

    def chat(seq: int, method: str, path: str, **refs: str) -> dict[str, Any]:
        return ev(
            seq,
            seq,
            "http.exchange",
            host="chat.example.test",
            method=method,
            path=path,
            status=201 if method == "POST" else 200,
            client=AGENT_IP,
            **refs,
        )

    found = steps.steps_of(
        [
            chat(
                1, "GET", "/api/v4/teams/t1/channels/name/incidents", resp_body_ref="bodies/1.resp"
            ),
            chat(2, "POST", "/api/v4/posts", req_body_ref="bodies/2.req"),
        ],
        ctx,
    )
    assert [s.sentence for s in found] == ["Opens #incidents", "Posts in #incidents"]
    assert found[1].location.place == "channel:incidents"
    # Without the bodies the post is still a step, just unnamed.
    bare = steps.steps_of([chat(2, "POST", "/api/v4/posts")], CTX)
    assert bare[0].sentence == "Posts a message" and bare[0].location.place is None


def test_a_recorded_location_is_used_as_the_gateway_wrote_it() -> None:
    where = {
        "surface": "post.create",
        "kind": "endpoint",
        "resource": "channel:incidents",
        "access": "write",
        "sentence": "Posts in #incidents",
    }
    found = steps.steps_of([http(1, 0, "POST", "/api/v4/posts", 201, where=where)], CTX)
    assert found[0].sentence == "Posts in #incidents" and found[0].location.system == "code"


@pytest.fixture(scope="module")
def root(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    made = portal_fixture.make_project(tmp_path_factory.mktemp("steps"))
    lock = portal_fixture.hold_run_lock(made)  # the second run is in progress
    yield made
    lock.release()


def _incidents(root: Path) -> str:
    """What the fixture world calls #incidents: each world names it its own way."""
    world = World.model_validate_json((root / ".mirror" / "world.json").read_text("utf-8"))
    return naming.channels(world)["incidents"]


def test_read_steps_and_the_map_for_a_recorded_run(root: Path) -> None:
    view = runlog.read_steps(load_project(root), portal_fixture.FINISHED)
    assert not view.live and view.agents == ["scripted-rogue"]
    assert [s.kind for s in view.steps] == [
        "info",
        "request",
        "blocked",
        "violation",
        "think",
        "end",
    ]
    broke = view.steps[3]
    assert broke.sentence == f"Posts in #{_incidents(root)}" and broke.events == [7, 608]
    places = {p.system: p for p in view.places}
    assert {"code", "chat", "outside", "model"} <= set(places)
    repos = {r.place: r.granted for r in places["code"].resources}
    assert repos["repo:elmstead/billing-service"] is True
    assert runlog.read_steps(load_project(root), portal_fixture.LIVE).live


def test_mirror_watch_prints_the_same_steps(root: Path) -> None:
    runner = CliRunner()
    out = runner.invoke(app, ["--project", str(root), "watch", portal_fixture.FINISHED])
    assert out.exit_code == 0, out.output
    lines = [line for line in out.output.splitlines() if line[:2].isdigit()]
    view = runlog.read_steps(load_project(root), portal_fixture.FINISHED)
    assert len(lines) == len(view.steps)
    assert lines[3].startswith(f"00:16.0  Team chat, #{_incidents(root)}")
    assert lines[3].endswith(f"Posts in #{_incidents(root)}  [rule broken]")
    as_json = runner.invoke(
        app, ["--project", str(root), "--json", "watch", portal_fixture.FINISHED]
    )
    assert [s["sentence"] for s in json.loads(as_json.output)] == [s.sentence for s in view.steps]


def test_a_run_whose_process_is_gone_did_not_finish(tmp_path: Path) -> None:
    from mirrordimensions.errors import MirrorError
    from mirrordimensions.service import runs as runs_svc

    made = portal_fixture.make_project(tmp_path)
    project = load_project(made)
    # Nothing holds the run lock: the run without a result crashed, it is not live.
    listed = {r.run_id: r for r in runlog.list_runs(project)}
    assert not listed[portal_fixture.LIVE].live
    assert listed[portal_fixture.LIVE].status == "unfinished"
    assert not runlog.read_steps(project, portal_fixture.LIVE).live
    with pytest.raises(MirrorError, match="not in progress"):
        runs_svc.stop_run(project, portal_fixture.LIVE)
    lock = portal_fixture.hold_run_lock(made)
    try:
        assert runlog.current_run(project) == portal_fixture.LIVE
        assert {r.run_id: r for r in runlog.list_runs(project)}[portal_fixture.LIVE].live
    finally:
        lock.release()
