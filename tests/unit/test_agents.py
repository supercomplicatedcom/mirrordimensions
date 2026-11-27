# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""Hosted agents: where they sit, what they are given, and who they act as."""

from __future__ import annotations

from pathlib import Path

import pytest
from test_world import manifest  # pyright: ignore[reportMissingImports, reportUnknownVariableType]

from mirrordimensions.agents import hosted
from mirrordimensions.config.agent import Agent
from mirrordimensions.config.loader import load_model
from mirrordimensions.errors import MirrorError
from mirrordimensions.network.egress_check import MASKED_PATHS
from mirrordimensions.network.sandbox import Plan
from mirrordimensions.service.agents import resolve_person
from mirrordimensions.twins.base import Identity
from mirrordimensions.world.denylist import findings
from mirrordimensions.world.generate import generate

EXAMPLE = (
    Path(__file__).resolve().parents[2] / "examples" / "agents" / "scripted-good" / "agent.yaml"
)
IDS = {
    "code": Identity(
        username="ana.silva",
        password="pw",
        token="t1",
        env={"GITEA_URL": "https://git.northfield.com", "GITEA_TOKEN": "t1"},
    ),
    "chat": Identity(
        username="ana.silva",
        password="pw",
        token="t2",
        env={"MATTERMOST_URL": "https://chat.northfield.com", "MATTERMOST_TOKEN": "t2"},
    ),
}


def test_the_reference_agent_file_is_valid() -> None:
    agent, problems = load_model(EXAMPLE, Agent)
    assert agent is not None, problems
    assert agent.mode == "hosted"
    assert agent.build == "."


def test_placement_is_stable_ordinary_and_clear_of_the_probe() -> None:
    plan = Plan(world="northfield", seed=1, company="Northfield", apps=[], model_hosts=[])
    first = hosted.placement(plan, "scripted-good")
    assert first == hosted.placement(plan, "scripted-good")
    assert first.name.startswith("ws-")
    assert first.ip.startswith("10.40.0.")
    assert 100 <= int(first.ip.rsplit(".", 1)[1]) < 140
    assert findings(first.name) == []


def test_environment_defaults_to_production_variables_and_fills_references() -> None:
    assert hosted.environment({}, IDS) == {**IDS["code"].env, **IDS["chat"].env}
    declared = {
        "FORGE": "${code.url}",
        "FORGE_PAT": "${code.token}",
        "CHAT_USER": "${chat.username}",
        "TEAM": "platform",
    }
    assert hosted.environment(declared, IDS) == {
        "FORGE": "https://git.northfield.com",
        "FORGE_PAT": "t1",
        "CHAT_USER": "ana.silva",
        "TEAM": "platform",
    }
    with pytest.raises(MirrorError, match="refer to 'wiki'"):
        hosted.environment({"WIKI": "${wiki.token}"}, IDS)


def test_the_container_gets_the_agent_position_hardening() -> None:
    plan = Plan(world="northfield", seed=1, company="Northfield", apps=[], model_hosts=[])
    where = hosted.placement(plan, "scripted-good")
    spec = hosted.spec(plan, where, "triage-bot:1.4", {"A": "b"}, None)
    assert spec.masked_paths == MASKED_PATHS
    assert spec.cap_add == []
    assert spec.dns == [plan.addr.dns_ip]
    assert spec.labels == {}  # nothing on the container names the mirror
    assert spec.hostname == where.name


def test_acts_as_a_role_picks_a_current_employee_deterministically() -> None:
    world = generate(manifest())
    agent, _ = load_model(EXAMPLE, Agent)
    assert agent is not None
    person = resolve_person(world, agent)
    assert "engineer" in person.roles
    assert person.left_ago is None
    assert resolve_person(world, agent) == person
    named = agent.model_copy(
        update={
            "acts_as": agent.acts_as.model_copy(update={"role": None, "person": person.username})
        }
    )  # type: ignore[union-attr]
    assert resolve_person(world, named) == person


def test_model_keys_are_placeholders_in_the_providers_form() -> None:
    from mirrordimensions.network.sandbox import ModelPlan

    plan = Plan(
        world="northfield", seed=7, company="Northfield", apps=[], model_hosts=["api.anthropic.com"]
    )
    plan.models = [
        ModelPlan(
            name="primary",
            provider="anthropic",
            host="api.anthropic.com",
            hosted_tools="block",
            credential_env="ANTHROPIC_API_KEY",
        )
    ]
    keys = hosted.model_placeholders(plan)
    key = keys["ANTHROPIC_API_KEY"]
    assert key.startswith("sk-ant-api03-")
    assert key.endswith("AA")
    assert len(key) == 108
    assert key == hosted.placeholder_key("anthropic", 7, "primary")  # stable for the world
    assert key != hosted.placeholder_key("anthropic", 8, "primary")
    assert findings(key) == []
