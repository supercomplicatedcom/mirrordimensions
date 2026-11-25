# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""M7: the portal's server. Access control, and each endpoint returning the service layer's
answer, against a project with a generated world and recorded runs (no engine)."""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from mirrordimensions.portal import server
from mirrordimensions.service import load_project
from mirrordimensions.service import runs as runs_svc

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import portal_fixture

PORT = 7499
BASE = f"http://127.0.0.1:{PORT}"
AUTH = {"Authorization": f"Bearer {portal_fixture.TOKEN}"}
WRITE = {**AUTH, "X-Mirror-Portal": "1"}


@pytest.fixture(scope="module")
def root(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    made = portal_fixture.make_project(tmp_path_factory.mktemp("portal"))
    lock = portal_fixture.hold_run_lock(made)  # the second run is in progress
    yield made
    lock.release()


@pytest.fixture
def client(root: Path, tmp_path: Path) -> Iterator[TestClient]:
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<!doctype html><title>Mirror</title>", encoding="utf-8")
    (static / "app.js").write_text("console.log(1)", encoding="utf-8")
    app = server.create_app(load_project(root), portal_fixture.TOKEN, PORT, static)
    with TestClient(app, base_url=BASE) as c:
        yield c


def test_nothing_is_served_without_the_token(client: TestClient) -> None:
    for path in ("/api/v1/project", "/api/v1/runs", "/environment", "/app.js"):
        assert client.get(path).status_code == 401
    assert (
        client.get("/api/v1/project", headers={"Authorization": "Bearer wrong"}).status_code == 401
    )
    assert client.get("/?token=wrong", follow_redirects=False).status_code == 401


def test_opening_the_address_once_signs_the_browser_in(client: TestClient) -> None:
    first = client.get(f"/?token={portal_fixture.TOKEN}", follow_redirects=False)
    assert first.status_code == 303 and first.headers["location"] == "/"
    cookie = first.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie
    assert client.get("/api/v1/project").status_code == 200  # the cookie is enough now
    assert client.get("/runs/whatever").text.startswith("<!doctype html>")  # the app routes it


def test_a_page_on_another_host_name_cannot_reach_it(client: TestClient) -> None:
    # DNS rebinding: a site that points its own name at 127.0.0.1 still sends its own Host.
    answer = client.get("/api/v1/project", headers={**AUTH, "Host": f"attacker.example:{PORT}"})
    assert answer.status_code == 421
    assert (
        client.get("/api/v1/project", headers={**AUTH, "Host": f"localhost:{PORT}"}).status_code
        == 200
    )


def test_changes_need_the_portal_header(client: TestClient) -> None:
    refused = client.post(f"/api/v1/runs/{portal_fixture.LIVE}/stop", headers=AUTH)
    assert refused.status_code == 403
    assert client.delete("/api/v1/agents/scripted-good", headers=AUTH).status_code == 403


def test_answers_carry_protective_headers(client: TestClient) -> None:
    answer = client.get("/api/v1/project", headers=AUTH)
    assert "default-src 'self'" in answer.headers["content-security-policy"]
    assert answer.headers["x-content-type-options"] == "nosniff"
    assert answer.headers["cache-control"] == "no-store"


def test_the_screens_read_live_project_data(client: TestClient, root: Path) -> None:
    project = client.get("/api/v1/project", headers=AUTH).json()
    assert project["name"] == "northfield-ops" and project["state"] == "built"
    graph = client.get("/api/v1/environment/graph", headers=AUTH).json()
    kinds = {n["kind"] for n in graph["nodes"]}
    assert {"agent", "gateway", "system"} <= kinds
    code = next(n for n in graph["nodes"] if n["id"] == "system:code")
    assert (
        code["granted_to"] == ["scripted-good", "scripted-rogue"]
        and code["visibility"] == "granted"
    )
    assert {"source": "gateway", "target": "system:code", "kind": "route", "label": ""} in graph[
        "edges"
    ]
    agents = {a["name"]: a for a in client.get("/api/v1/agents", headers=AUTH).json()}
    assert agents["scripted-rogue"]["last_run"] == portal_fixture.FINISHED
    world = client.get("/api/v1/world", headers=AUTH).json()
    assert len(world["people"]) >= 20 and world["canaries"]
    assert client.get("/api/v1/world/people", headers=AUTH).json()["canaries"] == []
    assert client.get("/api/v1/world/nope", headers=AUTH).status_code == 404
    scenarios = {s["id"]: s for s in client.get("/api/v1/scenarios", headers=AUTH).json()}
    assert scenarios["rotate-leaked-token"]["delivery_words"] == "an assigned issue"
    assert scenarios["rotate-leaked-token"]["suites"] == ["core"]
    runs = client.get("/api/v1/runs", headers=AUTH).json()
    assert [r["run_id"] for r in runs] == [
        portal_fixture.LIVE,
        portal_fixture.FINISHED,
    ]  # newest first
    assert runs[0]["live"] and runs[0]["status"] == "running"
    assert runs[1]["checks"] == 2 and runs[1]["checks_passed"] == 1
    health = client.get("/api/v1/health", headers=AUTH).json()
    assert health["state"] == "built" and health["doctor"] is None


def test_a_run_reads_a_page_at_a_time_and_finds_an_event(client: TestClient) -> None:
    run = portal_fixture.FINISHED
    result = client.get(f"/api/v1/runs/{run}", headers=AUTH).json()
    assert result["status"] == "failed"
    page = client.get(f"/api/v1/runs/{run}/events?limit=500", headers=AUTH).json()
    assert page["total"] == 609 and len(page["events"]) == 500
    assert (
        page["events"][0]["summary"].startswith("run started")
        and page["events"][0]["at"] == "00:00.0"
    )
    later = client.get(f"/api/v1/runs/{run}/events?limit=500&around=609", headers=AUTH).json()
    assert later["offset"] == 500 and later["events"][-1]["seq"] == 609
    only = client.get(f"/api/v1/runs/{run}/events?source=gateway,egress", headers=AUTH).json()
    assert [e["seq"] for e in only["events"]] == [5, 6, 7]
    text = client.get(f"/api/v1/runs/{run}/events?q=1.1.1.1", headers=AUTH).json()
    assert [e["seq"] for e in text["events"]] == [6]
    bad = client.get(f"/api/v1/runs/{run}/events?source=nowhere", headers=AUTH)
    assert bad.status_code == 400 and "Unknown source" in bad.json()["what"]


def test_stored_bodies_are_served_as_text_never_as_a_page(client: TestClient) -> None:
    run = portal_fixture.FINISHED
    body = client.get(f"/api/v1/runs/{run}/bodies/bodies/100-1.req", headers=AUTH)
    assert body.status_code == 200 and "pk_live_planted" in body.text
    assert body.headers["content-type"].startswith("application/json")
    assert body.headers["content-security-policy"] == "default-src 'none'"
    for name in ("..%2Fresult.json", "..%2F..%2Fresult.json", "missing"):
        answer = client.get(f"/api/v1/runs/{run}/bodies/bodies/{name}", headers=AUTH)
        assert answer.status_code in (400, 404) and '"isolation"' not in answer.text
    assert client.get(f"/api/v1/runs/{run}/bodies/etc/passwd", headers=AUTH).status_code == 400


def test_the_live_timeline_streams_until_the_run_ends(client: TestClient, root: Path) -> None:
    run = portal_fixture.FINISHED
    with client.stream(
        "GET", f"/api/v1/runs/{run}/events/stream?type=check.result,run.end", headers=AUTH
    ) as stream:
        assert stream.headers["content-type"].startswith("text/event-stream")
        text = "".join(stream.iter_text())
    assert text.count("event: event") == 2 and text.endswith("event: end\ndata: {}\n\n")
    assert "id: 608" in text


def test_stopping_a_run_asks_it_to_end(client: TestClient, root: Path) -> None:
    assert client.post(f"/api/v1/runs/{portal_fixture.LIVE}/stop", headers=WRITE).json() == {
        "stopping": portal_fixture.LIVE
    }
    assert (root / ".mirror" / "runs" / portal_fixture.LIVE / runs_svc.STOP_FILE).is_file()
    ended = client.post(f"/api/v1/runs/{portal_fixture.FINISHED}/stop", headers=WRITE)
    assert ended.status_code == 400 and "already ended" in ended.json()["what"]
    (root / ".mirror" / "runs" / portal_fixture.LIVE / runs_svc.STOP_FILE).unlink()


def test_reach_sets_grants_against_the_last_run(client: TestClient) -> None:
    rogue = client.get("/api/v1/agents/scripted-rogue/reach", headers=AUTH).json()
    assert rogue["run_id"] == portal_fixture.FINISHED
    good = client.get("/api/v1/agents/scripted-good/reach", headers=AUTH).json()
    assert good["run_id"] is None  # never ran: its grants alone
    repos = {r["repo"].split("/")[1]: r["granted"] for r in good["access"]["repositories"]}
    assert repos == {"billing-service": "write", "platform-docs": "read"}
    assert all(not r["how"] for r in good["access"]["repositories"])


def test_a_source_checkout_without_built_files_says_how_to_build_them(
    root: Path, tmp_path: Path
) -> None:
    app = server.create_app(load_project(root), portal_fixture.TOKEN, PORT, tmp_path / "none")
    with TestClient(app, base_url=BASE) as c:
        page = c.get("/environment", headers=AUTH)
    assert page.status_code == 503 and "npm --prefix src/mirrordimensions/portal/web" in page.text


def test_a_body_name_cannot_leave_the_runs_folder(root: Path) -> None:
    from mirrordimensions.errors import MirrorError
    from mirrordimensions.service import runlog

    project = load_project(root)
    for ref in ("bodies/..", "bodies/../result.json", "model/.", "../result.json", "result.json"):
        with pytest.raises(MirrorError):
            runlog.read_body(project, portal_fixture.FINISHED, ref)


def test_the_live_view_reads_steps_and_streams_them(client: TestClient) -> None:
    run = portal_fixture.FINISHED
    view = client.get(f"/api/v1/runs/{run}/steps", headers=AUTH).json()
    assert view["live"] is False and view["agents"] == ["scripted-rogue"]
    assert [s["kind"] for s in view["steps"]] == [
        "info",
        "request",
        "blocked",
        "violation",
        "think",
        "end",
    ]
    assert {p["system"] for p in view["places"]} >= {"code", "chat", "model", "outside"}
    with client.stream("GET", f"/api/v1/runs/{run}/steps/stream", headers=AUTH) as stream:
        assert stream.headers["content-type"].startswith("text/event-stream")
        text = "".join(stream.iter_text())
    # The post is sent when it happens and again when the check finds it broke a rule.
    assert text.count("event: step") == 7 and text.endswith("event: end\ndata: {}\n\n")
    assert text.count('"index":3') == 2 and '"kind":"violation"' in text
    assert client.get("/api/v1/runs/r_nosuchrun/steps", headers=AUTH).status_code == 404


@pytest.fixture
def editable(tmp_path: Path) -> Iterator[tuple[TestClient, Path]]:
    """A project of its own, just built, for tests that edit it."""
    from mirrordimensions.service.agents import _manifest  # pyright: ignore[reportPrivateUsage]
    from mirrordimensions.service.changes import record_built

    made = portal_fixture.make_project(tmp_path / "own")
    record_built(load_project(made), _manifest(load_project(made)))
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<!doctype html>", encoding="utf-8")
    app = server.create_app(load_project(made), portal_fixture.TOKEN, PORT, static)
    with TestClient(app, base_url=BASE) as c:
        yield c, made


def test_visibility_edits_become_pending_changes(editable: tuple[TestClient, Path]) -> None:
    client, made = editable
    assert client.get("/api/v1/changes", headers=AUTH).json() == []
    assert (
        client.patch(
            "/api/v1/environment/apps/chat", json={"visibility": "denied"}, headers=AUTH
        ).status_code
        == 403
    )
    change = client.patch(
        "/api/v1/environment/apps/chat", json={"visibility": "denied"}, headers=WRITE
    ).json()
    assert (change["after"], change["applies"]) == ("denied", "next run")
    assert "visibility: denied" in (made / "mirror.yaml").read_text(encoding="utf-8")
    pending = client.get("/api/v1/changes", headers=AUTH).json()
    assert [c["what"] for c in pending] == ["Team chat: visibility granted to denied"]
    assert client.get("/api/v1/project", headers=AUTH).json()["pending_changes"] == 1
    graph = client.get("/api/v1/environment/graph", headers=AUTH).json()
    chat = next(n for n in graph["nodes"] if n["id"] == "system:chat")
    assert chat["visibility"] == "denied"
    bad = client.patch(
        "/api/v1/environment/apps/chat", json={"visibility": "hidden"}, headers=WRITE
    )
    assert bad.status_code == 400 and "not a visibility" in bad.json()["what"]


def test_the_portal_and_the_command_line_make_the_same_edit(
    editable: tuple[TestClient, Path], tmp_path: Path
) -> None:
    from typer.testing import CliRunner

    from mirrordimensions.cli.app import app as cli

    client, made = editable
    client.patch("/api/v1/environment/apps/chat", json={"visibility": "present"}, headers=WRITE)
    by_portal = (made / "mirror.yaml").read_text(encoding="utf-8")
    other = portal_fixture.make_project(tmp_path / "cli")
    out = CliRunner().invoke(cli, ["--project", str(other), "set", "visibility", "chat", "present"])
    assert out.exit_code == 0, out.output
    assert (other / "mirror.yaml").read_text(encoding="utf-8") == by_portal


def test_grants_and_rules_are_edited_through_the_portal(editable: tuple[TestClient, Path]) -> None:
    client, made = editable
    change = client.patch(
        "/api/v1/agents/scripted-good/grants",
        json={"resource": "code/infra-config", "grant": "read"},
        headers=WRITE,
    ).json()
    assert (change["before"], change["after"]) == (None, "read")
    assert "infra-config: read" in (made / "agents" / "scripted-good.yaml").read_text("utf-8")
    systems = {s["id"]: s for s in client.get("/api/v1/systems", headers=AUTH).json()}
    assert systems["code"]["twin"] and systems["code"]["rules"] == 0
    rule = {"match": {"surface": "repo.search"}, "output": {"delay_ms": [800, 2500]}}
    saved = client.put("/api/v1/systems/code/rules/slow-search", json=rule, headers=WRITE).json()
    assert (
        saved["applies"] == "next run" and saved["what"] == "Code hosting: rule slow-search added"
    )
    detail = client.get("/api/v1/systems/code", headers=AUTH).json()
    search = next(s for s in detail["surfaces"] if s["id"] == "repo.search")
    assert search["customized_by"] == ["slow-search"]
    # A rule that answers by itself is shown without asking the product.
    failing = {"match": {"surface": "repo.read"}, "output": {"fail": {"rate": 1.0}}}
    client.put("/api/v1/systems/code/rules/always-down", json=failing, headers=WRITE)
    tried = client.post(
        "/api/v1/systems/code/try",
        json={"method": "GET", "path": "/api/v1/repos/elmstead/billing-service"},
        headers=WRITE,
    ).json()
    assert tried["from_rule"] and tried["status"] == 502
    assert tried["rules_fired"] == [{"rule": "always-down", "changed": ["fail"]}]
    wrong = client.put(
        "/api/v1/systems/code/rules/other", json={**rule, "name": "x"}, headers=WRITE
    )
    assert wrong.status_code == 400
    invalid = client.put(
        "/api/v1/systems/code/rules/broken", json={"match": {"surface": "nope"}}, headers=WRITE
    )
    assert invalid.status_code == 400
    gone = client.delete("/api/v1/systems/code/rules/slow-search", headers=WRITE).json()
    assert gone["after"] is None


def test_applying_changes_streams_its_steps(
    editable: tuple[TestClient, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    from mirrordimensions.service import environment as env

    client, _ = editable

    def fake(_project: object, on_step: Any = None) -> env.ApplyResult:
        on_step("Rebuilding from the first stage the changes affect")
        on_step("2. Set up the sealed network")
        return env.ApplyResult(rebuilt=True, applied=[], waiting=[])

    monkeypatch.setattr(env, "apply_changes", fake)
    assert client.post("/api/v1/build", headers=AUTH).status_code == 403
    started = client.post("/api/v1/build", headers=WRITE)
    assert started.status_code == 200 and started.json()["error"] is None
    with client.stream("GET", "/api/v1/build/stream", headers=AUTH) as stream:
        text = "".join(stream.iter_text())
    assert text.count("event: step") == 2 and '"rebuilt":true' in text
    assert client.get("/api/v1/build", headers=AUTH).json()["running"] is False
