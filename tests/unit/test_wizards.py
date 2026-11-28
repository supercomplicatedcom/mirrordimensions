# SPDX-License-Identifier: Apache-2.0
"""M7: the portal's two wizards write the same files as the command line, keep drafts that
resume, and the portal switches to the world it creates (decision 0022)."""

from __future__ import annotations

import shlex
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from ruamel.yaml import YAML
from typer.testing import CliRunner

from mirrordimensions.cli.app import app as cli
from mirrordimensions.portal import server
from mirrordimensions.service import load_project, worlddef

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import portal_fixture

PORT = 7499
BASE = f"http://127.0.0.1:{PORT}"
WRITE = {"Authorization": f"Bearer {portal_fixture.TOKEN}", "X-Mirror-Portal": "1"}


@pytest.fixture
def portal(tmp_path: Path) -> Iterator[tuple[TestClient, Path]]:
    worlds = tmp_path / "worlds"
    worlds.mkdir()
    root = portal_fixture.make_project(worlds)
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<!doctype html>", encoding="utf-8")
    app = server.create_app(load_project(root), portal_fixture.TOKEN, PORT, static)
    with TestClient(app, base_url=BASE) as client:
        yield client, root


def _yaml(path: Path) -> dict[str, Any]:
    return YAML(typ="safe").load(path.read_text(encoding="utf-8"))


def test_the_world_wizard_writes_a_draft_at_every_step(portal: tuple[TestClient, Path]) -> None:
    client, root = portal
    view = client.post("/api/v1/worlds/draft", json={"folder": "acme-ops"}, headers=WRITE).json()
    folder = Path(view["folder"])
    assert folder == root.parent / "acme-ops" and view["step"] == 1
    assert not (folder / "mirror.yaml").exists()  # nothing written before an answer

    def step(**fields: Any) -> dict[str, Any]:
        answer = client.patch(
            "/api/v1/worlds/draft", json={"folder": "acme-ops", "fields": fields}, headers=WRITE
        )
        assert answer.status_code == 200, answer.text
        return answer.json()

    step(template="software-team", step=2)
    written = _yaml(folder / "mirror.yaml")
    assert written["status"] == "draft" and written["apps"][0]["id"] == "code"
    view = step(
        seed=4242,
        company_name="Halvorsen Freight",
        industry="logistics",
        people=40,
        tidiness="messy",
        step=3,
    )
    assert view["company"]["domain"] == "halvorsen-freight.com"
    assert [s["hostname"] for s in view["systems"]] == [
        "git.halvorsen-freight.com",
        "chat.halvorsen-freight.com",
    ]
    view = step(links={"announce": False}, data={"issues": 90}, step=5)
    assert "  issues: 90\n" in view["yaml"] and "announce" not in view["yaml"]
    assert _yaml(folder / "mirror.yaml")["company"]["size"] == 40
    # Another suggestion replaces the company; the same seed always offers the same ones.
    other = step(another_company=True)["company"]
    assert other["name"] != "Halvorsen Freight"
    assert step(company_name="Halvorsen Freight")["company"]["name"] == "Halvorsen Freight"
    bad = client.patch(
        "/api/v1/worlds/draft",
        json={"folder": "acme-ops", "fields": {"domain": "not a domain"}},
        headers=WRITE,
    )
    assert bad.status_code == 400
    # The draft resumes where it was left.
    again = client.post("/api/v1/worlds/draft", json={"folder": "acme-ops"}, headers=WRITE).json()
    assert again["step"] == 5 and again["draft"]["people"] == 40


def test_the_portal_and_the_command_line_write_the_same_world(
    portal: tuple[TestClient, Path], tmp_path: Path
) -> None:
    client, root = portal
    fields = {
        "template": "software-team",
        "seed": 4242,
        "company_name": "Halvorsen Freight",
        "industry": "logistics",
        "people": 40,
        "history": 90,
        "tidiness": "messy",
        "links": {"announce": False},
        "data": {"issues": 90, "canaries": 5},
    }
    client.post("/api/v1/worlds/draft", json={"folder": "acme"}, headers=WRITE)
    view = client.patch(
        "/api/v1/worlds/draft", json={"folder": "acme", "fields": fields}, headers=WRITE
    ).json()
    from mirrordimensions.service import worlds as worlds_svc

    made = worlds_svc.finish(load_project(root), "acme")
    by_portal = (made / "mirror.yaml").read_text(encoding="utf-8")
    assert "status:" not in by_portal  # defined now
    elsewhere = tmp_path / "cli"
    elsewhere.mkdir()
    words = shlex.split(view["command"])[1:]  # the command the wizard shows
    out = CliRunner().invoke(cli, [*words[:2], str(elsewhere / "acme"), *words[3:]])
    assert out.exit_code == 0, out.output
    assert (elsewhere / "acme" / "mirror.yaml").read_text(encoding="utf-8") == by_portal


def test_a_folder_that_holds_a_world_is_not_overwritten(portal: tuple[TestClient, Path]) -> None:
    client, root = portal
    taken = client.post("/api/v1/worlds/draft", json={"folder": root.name}, headers=WRITE)
    assert taken.status_code == 400 and "already holds a world" in taken.json()["what"]
    odd = client.post("/api/v1/worlds/draft", json={"folder": "../elsewhere"}, headers=WRITE)
    assert odd.status_code == 400


def test_creating_a_world_shows_each_stage_then_the_portal_serves_it(
    portal: tuple[TestClient, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    from mirrordimensions.service import world as world_svc

    client, root = portal

    def fake_create(_project: Any, on_stage: Any = None, **_: Any) -> int:
        for number, stage in enumerate(worlddef.STAGES, start=1):
            on_stage(f"{number}. {stage}")
        return len(worlddef.STAGES)

    monkeypatch.setattr(world_svc, "create_world", fake_create)
    client.post("/api/v1/worlds/draft", json={"folder": "acme"}, headers=WRITE)
    client.patch(
        "/api/v1/worlds/draft",
        json={"folder": "acme", "fields": {"template": "software-team", "seed": 77}},
        headers=WRITE,
    )
    assert client.post("/api/v1/worlds/create", json={"folder": "acme"}).status_code == 401
    started = client.post("/api/v1/worlds/create", json={"folder": "acme"}, headers=WRITE)
    assert started.status_code == 200
    with client.stream("GET", "/api/v1/worlds/create/stream", headers=WRITE) as stream:
        text = "".join(stream.iter_text())
    assert text.count("event: step") == 9 and "8. Ready" in text and '"last_stage":8' in text
    project = client.get("/api/v1/project", headers=WRITE).json()
    assert project["root"] == str(root.parent / "acme")
    listed = {Path(w["folder"]).name: w for w in client.get("/api/v1/worlds", headers=WRITE).json()}
    assert listed["acme"]["current"] and not listed[root.name]["current"]
    back = client.post("/api/v1/worlds/switch", json={"folder": root.name}, headers=WRITE).json()
    assert back["current"] and back["name"] == "northfield-ops"
    assert client.get("/api/v1/project", headers=WRITE).json()["root"] == str(root)


def test_onboarding_in_the_portal_writes_the_same_agent_file(
    portal: tuple[TestClient, Path], tmp_path: Path
) -> None:
    client, root = portal
    assert (
        client.post("/api/v1/agents/drafts", json={"name": "ops-helper"}, headers=WRITE).json()[
            "step"
        ]
        == 1
    )
    listed = {a["name"]: a for a in client.get("/api/v1/agents", headers=WRITE).json()}
    assert listed["ops-helper"]["state"] == "draft, step 1 of 6"

    def step(n: int, **body: Any) -> dict[str, Any]:
        answer = client.patch(
            "/api/v1/agents/drafts/ops-helper", json={"step": n, **body}, headers=WRITE
        )
        assert answer.status_code == 200, answer.text
        return answer.json()

    assert step(1, fields={"mode": "hosted", "image": "triage-bot:1.4"})["step"] == 2
    assert step(2, model={"where": "none"})["step"] == 3
    step(3, fields={"acts_as": {"role": "engineer"}})
    defaults = client.get("/api/v1/roles/engineer/defaults", headers=WRITE).json()
    assert defaults["person"]["username"] and defaults["lines"]
    step(4, fields={"grants": {"code": {"repos": {"billing-service": "write"}}}})
    done = step(5, fields={"wake": {"type": "command", "command": ["python", "/opt/agent.py"]}})
    assert done["step"] == 6
    # The file is complete after step 5; step 6 checks it. Another interface finds it so.
    assert client.get("/api/v1/agents/drafts/ops-helper", headers=WRITE).json()["step"] == 7
    by_portal = (root / "agents" / "ops-helper.yaml").read_text(encoding="utf-8")
    # The same answers through `mirror agent new`, in a copy of the project.
    other = portal_fixture.make_project(tmp_path / "copy")
    out = CliRunner().invoke(
        cli,
        [
            "--project",
            str(other),
            "agent",
            "new",
            "ops-helper",
            "--mode",
            "hosted",
            "--image",
            "triage-bot:1.4",
            "--model",
            "none",
            "--role",
            "engineer",
            "--grant",
            "code.repos.billing-service=write",
            "--wake",
            "command",
            "--command",
            "python /opt/agent.py",
            "--no-check",
        ],
    )
    assert out.exit_code == 0, out.output
    assert (other / "agents" / "ops-helper.yaml").read_text(encoding="utf-8") == by_portal
    wrong = client.patch(
        "/api/v1/agents/drafts/ops-helper",
        json={"step": 1, "fields": {"mode": "remote"}},
        headers=WRITE,
    )
    # A remote agent's reduced protections are accepted before onboarding goes on.
    assert wrong.status_code == 400 and "must be accepted first" in wrong.json()["what"]
    assert "detected but not blocked" in wrong.json()["why"]


def test_a_draft_world_is_not_created(portal: tuple[TestClient, Path]) -> None:
    from mirrordimensions.errors import MirrorError
    from mirrordimensions.service import world as world_svc

    client, root = portal
    client.post("/api/v1/worlds/draft", json={"folder": "half"}, headers=WRITE)
    client.patch(
        "/api/v1/worlds/draft", json={"folder": "half", "fields": {"step": 2}}, headers=WRITE
    )
    with pytest.raises(MirrorError, match="still a draft"):
        world_svc.create_world(load_project(root.parent / "half"))


def test_a_browser_agent_is_onboarded_the_same_way_in_both(
    portal: tuple[TestClient, Path], tmp_path: Path
) -> None:
    """A browser agent's program may need a command to start it, as a hosted one's may."""
    client, root = portal
    client.post("/api/v1/agents/drafts", json={"name": "desk"}, headers=WRITE)
    for n, body in (
        (1, {"fields": {"mode": "browser", "image": "desk-helper:0.9"}}),
        (2, {"model": {"where": "none"}}),
        (3, {"fields": {"acts_as": {"role": "engineer"}}}),
        (4, {"fields": {"grants": {"code": {"repos": {"billing-service": "write"}}}}}),
        (5, {"fields": {"wake": {"type": "command", "command": ["python", "/opt/desk/agent.py"]}}}),
    ):
        answer = client.patch("/api/v1/agents/drafts/desk", json={"step": n, **body}, headers=WRITE)
        assert answer.status_code == 200, answer.text
    by_portal = (root / "agents" / "desk.yaml").read_text(encoding="utf-8")
    assert "mode: browser" in by_portal and "/opt/desk/agent.py" in by_portal
    other = portal_fixture.make_project(tmp_path / "copy")
    out = CliRunner().invoke(
        cli,
        [
            "--project", str(other), "agent", "new", "desk",
            "--mode", "browser", "--image", "desk-helper:0.9", "--model", "none",
            "--role", "engineer", "--grant", "code.repos.billing-service=write",
            "--wake", "command", "--command", "python /opt/desk/agent.py", "--no-check",
        ],
    )  # fmt: skip
    assert out.exit_code == 0, out.output
    assert (other / "agents" / "desk.yaml").read_text(encoding="utf-8") == by_portal
