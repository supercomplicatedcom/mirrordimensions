# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""Whole runs against a live world (build spec, M5): set MIRROR_TEST_PROJECT to a project
whose world is created and up, with the reference agents added."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from mirrordimensions.project import Project
from mirrordimensions.service import runs
from mirrordimensions.twins.base import RunContext

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("MIRROR_TEST_PROJECT") is None,
        reason="set MIRROR_TEST_PROJECT to a project with a running world",
    ),
]


def project() -> Project:
    return Project(root=Path(os.environ["MIRROR_TEST_PROJECT"]))


def test_a_change_the_gateway_did_not_see_makes_coverage_incomplete() -> None:
    """A write straight to a twin, bypassing the gateway, while the agent runs."""

    def hidden_write(code: RunContext, chat: RunContext) -> None:
        resp = code.relay.request(
            "POST",
            f"http://{code.ctx.app_ip}:3000/api/v1/repos/{code.world.org}/infra-config/issues",
            body={"title": "Quarterly access review"},
            basic=("git-admin", code.ctx.secrets["admin_password"]),
            headers={"Sudo": code.acts_as.username},
        )
        assert resp.status == 201, resp.body

    outcome, result = runs.run_with_actor(
        project(), "rotate-leaked-token", "scripted-good", during=hidden_write
    )
    state = result.coverage["reconciliations"]["state_against_requests"]
    assert not state["passed"]
    assert any("infra-config" in item["object"] for item in state["unexplained"])
    assert (
        result.coverage["status"] == "incomplete"
        and "cannot be used as evidence" in result.coverage["warning"]
    )
    assert runs.exit_code([outcome]) == 4


def test_scripted_rogue_fails_with_each_violation_listed() -> None:
    (outcome,) = runs.run(project(), "private-file-request", "scripted-rogue")
    result = runs.load_result(project(), outcome.run_id)
    assert outcome.status == "failed"
    failed = {c["check"] for c in result.checks if not c["passed"]}
    assert {"gitea.token_used", "gitea.request_made", "mattermost.message_contains"} <= failed
    assert any(e["kind"] == "connection" for e in result.egress)  # the blocked outside attempts
    assert any(e["kind"] == "lookup" for e in result.egress)
    assert any(
        "infra-config" in s["object"] or "billing-service" in s["object"]
        for s in result.side_effects
    )
    assert any(c["canary"] == "canary.record" for c in result.canaries)


def test_a_run_stops_cleanly_at_max_minutes_and_still_writes_a_result() -> None:
    (outcome,) = runs.run(project(), "answer-from-docs", "slow-poke", max_minutes=1)
    result = runs.load_result(project(), outcome.run_id)
    assert outcome.status == "stopped"
    assert result.reason == "stopped at max_minutes (1)"
    assert (Path(outcome.path) / "events.jsonl").is_file()
