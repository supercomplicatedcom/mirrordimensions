# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""Exact grants (decision 0020): for a run, the person the agent acts as has only what the
agent file grants, and a run whose work arrives somewhere ungranted is refused up front."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

from mirrordimensions.twins.base import TwinContext
from mirrordimensions.twins.gitea.adapter import Gitea
from mirrordimensions.twins.mattermost.adapter import Mattermost
from mirrordimensions.twins.relay import Response

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import portal_fixture


class FakeRelay:
    """Answers requests from a table of (method, path) -> (status, body); records them."""

    def __init__(self, answers: dict[tuple[str, str], tuple[int, Any]]) -> None:
        self.answers = answers
        self.calls: list[tuple[str, str]] = []

    def request(self, method: str, url: str, **_: Any) -> Response:
        path = "/" + url.split("/", 3)[3]
        self.calls.append((method, path))
        status, body = self.answers.get((method, path), (404, None))
        return Response(status, json.dumps(body).encode() if body is not None else b"")


def ctx() -> TwinContext:
    return TwinContext(
        app_id="code",
        hostname="git.example.test",
        company="Elmstead Mutual",
        seed=1,
        network="apps",
        dns=[],
        app_ip="10.41.0.10",
        db_ip="10.41.0.11",
        app_container="app-01",
        db_container="db-01",
        secrets={"user_password": "pw", "admin_password": "pw"},
    )


def test_gitea_takes_the_person_out_of_teams_and_ungranted_repositories() -> None:
    org = "elmstead"
    relay = FakeRelay(
        {
            ("GET", f"/api/v1/orgs/{org}/teams?limit=50&page=1"): (200, [{"id": 1}, {"id": 2}]),
            ("GET", "/api/v1/teams/1/members/astrid"): (200, {"login": "astrid"}),
            ("GET", "/api/v1/teams/2/members/astrid"): (404, None),
            ("DELETE", "/api/v1/teams/1/members/astrid"): (204, None),
            ("GET", f"/api/v1/orgs/{org}/repos?limit=50&page=1"): (
                200,
                [{"full_name": f"{org}/billing-service"}, {"full_name": f"{org}/infra-config"}],
            ),
            ("GET", f"/api/v1/repos/{org}/infra-config/collaborators/astrid"): (204, None),
            ("DELETE", f"/api/v1/repos/{org}/infra-config/collaborators/astrid"): (204, None),
        }
    )
    Gitea()._only_granted(relay, ctx(), "astrid", org, {f"{org}/billing-service"})  # pyright: ignore[reportPrivateUsage, reportArgumentType]
    deleted = [path for method, path in relay.calls if method == "DELETE"]
    assert deleted == [
        "/api/v1/teams/1/members/astrid",
        f"/api/v1/repos/{org}/infra-config/collaborators/astrid",
    ]
    # A granted repository is never checked, let alone removed.
    assert not any("billing-service/collaborators" in path for _, path in relay.calls)


def test_mattermost_keeps_granted_channels_and_the_default_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mm = Mattermost()
    calls: list[tuple[str, str]] = []
    posts = {
        "c-eng": {
            "posts": {
                "p1": {
                    "id": "p1",
                    "type": "system_remove_from_channel",
                    "props": {"removedUserId": "u1"},
                },
                "p2": {"id": "p2", "type": "", "props": {}},  # someone's message: kept
                "p3": {
                    "id": "p3",
                    "type": "system_remove_from_channel",
                    "props": {"removedUserId": "u9"},
                },
            }
        },
        "c-inc": {
            "posts": {
                "p4": {
                    "id": "p4",
                    "type": "system_add_to_channel",
                    "props": {"addedUserId": "u1", "userId": "admin"},
                },
            }
        },
    }

    def api(
        _relay: object, _ctx: object, method: str, path: str, body: Any = None, **_: Any
    ) -> Any:
        calls.append((method, path))
        if path == "/users/u1/teams/t1/channels":
            return [
                {"id": "c-town", "name": "town-square", "type": "O"},
                {"id": "c-inc", "name": "incidents", "type": "O"},
                {"id": "c-eng", "name": "engineering", "type": "O"},
                {"id": "c-dm", "name": "u1__u2", "type": "D"},  # a direct message: the person's own
            ]
        if path.startswith("/channels/") and path.endswith("/posts?per_page=20"):
            return posts.get(path.split("/")[2], {})
        if path == "/users/u1/tokens":
            return [] if method == "GET" else {"token": "t"}
        return {}

    monkeypatch.setattr(mm, "api", api)
    monkeypatch.setattr(mm, "ensure_team", lambda *_a, **_k: "t1")
    monkeypatch.setattr(
        mm, "ensure_channel", lambda _r, _c, _t, name, **_k: {"incidents": "c-inc"}[name]
    )
    monkeypatch.setattr(mm, "admin_token", lambda *_a: "admin")
    relay = FakeRelay({("GET", "/api/v4/users/username/astrid"): (200, {"id": "u1"})})
    mm.issue_identity(
        relay,
        ctx(),
        "astrid",
        "Astrid Mbeki",
        "a@x",
        {"team": "elmstead", "channels": ["incidents"]},
    )  # pyright: ignore[reportArgumentType]
    removed = [p for m, p in calls if m == "DELETE" and p.startswith("/channels/")]
    assert removed == ["/channels/c-eng/members/u1"]  # not town-square, not the DM
    deleted_posts = sorted(p for m, p in calls if m == "DELETE" and p.startswith("/posts/"))
    assert deleted_posts == ["/posts/p1", "/posts/p4"]  # only the announcements about this person


def test_a_run_needs_the_agent_granted_where_its_work_arrives(tmp_path: Path) -> None:
    from mirrordimensions.errors import MirrorError
    from mirrordimensions.runner import scenario as scenario_mod
    from mirrordimensions.service import load_project
    from mirrordimensions.service.agents import load_agent
    from mirrordimensions.service.runs import check_reach
    from mirrordimensions.service.sandbox import world_plan

    project = load_project(portal_fixture.make_project(tmp_path))
    plan = world_plan(project)
    good, _ = load_agent(project, "scripted-good")
    core = scenario_mod.builtin()
    # The example agent can reach the work of every built-in scenario.
    for scen in core.values():
        check_reach(plan, good, scen)
    narrow = good.model_copy(update={"grants": {"code": good.grants["code"]}})
    with pytest.raises(MirrorError) as refused:
        check_reach(plan, narrow, core["merge-duplicate-issues"])
    assert "a system the agent file does not grant at all" in refused.value.why
    fewer = good.model_copy(update={"grants": {**good.grants, "chat": {"channels": ["incidents"]}}})
    with pytest.raises(MirrorError) as missing:
        check_reach(plan, fewer, core["merge-duplicate-issues"])
    assert "It arrives in engineering on chat;" in missing.value.why
    assert "agents/scripted-good.yaml under chat.channels" in missing.value.fix
    check_reach(plan, fewer, core["rotate-leaked-token"])  # an issue in a granted repository
