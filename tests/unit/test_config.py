# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""The file formats accept the shapes in the build spec and reject what they should."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest
from pydantic import ValidationError

from mirrordimensions.config import SCHEMAS, Agent, Event, Manifest, Result, Scenario

COMPANY: dict[str, Any] = {
    "name": "Northfield Logistics",
    "domain": "northfield-logistics.com",
    "seed": 48213,
}


def manifest(**extra: Any) -> dict[str, Any]:
    return {"version": 1, "name": "northfield-ops", "company": COMPANY, **extra}


def test_full_manifest_union() -> None:
    m = Manifest.model_validate(
        manifest(
            apps=[
                {
                    "id": "code",
                    "kind": "code-hosting",
                    "product": "gitea",
                    "hostname": "git.northfield-logistics.com",
                    "settings": {"default_branch": "main"},
                    "data": {"repositories": 6},
                    "rules": [
                        {
                            "name": "slow-search",
                            "match": {"surface": "repo.search"},
                            "output": {"delay_ms": [800, 2500]},
                        }
                    ],
                },
                {
                    "id": "chat",
                    "product": "mattermost",
                    "hostname": "chat.northfield-logistics.com",
                },
                {
                    "id": "tools",
                    "kind": "mcp-server",
                    "hostname": "mcp.northfield-logistics.com",
                    "serves": {"tools_from": {"file": "tools.json"}, "backed_by": ["code", "chat"]},
                },
                {
                    "id": "building-access",
                    "kind": "device-platform",
                    "hostname": "access.northfield-logistics.com",
                },
            ],
            links=[{"announce": {"from": "code", "to": "chat", "channel": "engineering"}}],
            data={"repositories": 6, "issues": 150, "messages": 2000, "canaries": 3},
            models=[
                {
                    "name": "primary",
                    "provider": "anthropic",
                    "host": "api.anthropic.com",
                    "credential": {"from_env": "ANTHROPIC_API_KEY"},
                },
                {
                    "name": "local",
                    "provider": "self-hosted",
                    "host": "llm.northfield-logistics.com",
                    "upstream": "10.20.4.17:8000",
                },
            ],
            sites=[
                {"id": "hq", "name": "Headquarters", "floors": [{"id": "f1", "rooms": ["lobby"]}]}
            ],
            devices=[
                {
                    "id": "main-entrance",
                    "type": "door-lock",
                    "at": "hq/f1/lobby",
                    "platform": "building-access",
                }
            ],
        )
    )
    assert [a.id for a in m.apps] == ["code", "chat", "tools", "building-access"]


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        (
            {
                "apps": [
                    {"id": "a", "product": "gitea", "hostname": "git.x.com"},
                    {"id": "b", "product": "gitea", "hostname": "Git.X.com"},
                ]
            },
            "unique ignoring case",
        ),
        ({"apps": [{"id": "a", "hostname": "git.x.com"}]}, "needs a kind, a product"),
        (
            {
                "apps": [
                    {"id": "a", "product": "gitea", "hostname": "git.x.com", "visibility": "hidden"}
                ]
            },
            "visibility",
        ),
        ({"models": [{"name": "m", "provider": "self-hosted", "host": "llm.x.com"}]}, "upstream"),
        (
            {
                "apps": [
                    {
                        "id": "a",
                        "product": "gitea",
                        "hostname": "git.x.com",
                        "serves": {"tools_from": {}},
                    }
                ]
            },
            "only allowed on kind: mcp-server",
        ),
        ({"colour": "blue"}, "Extra inputs"),
    ],
)
def test_manifest_rejects(extra: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        Manifest.model_validate(manifest(**extra))


def test_agent_complete_and_draft() -> None:
    Agent.model_validate(
        {
            "name": "ops-assistant",
            "mode": "hosted",
            "acts_as": {"role": "engineer"},
            "image": "registry.northfield.internal/ops:1.4",
            "wake": {"type": "command", "command": ["python", "-m", "assistant"]},
            "grants": {"code": {"repos": {"billing-service": "write"}}},
        }
    )
    Agent.model_validate({"name": "half-done", "mode": "browser", "status": "draft", "step": 3})
    with pytest.raises(ValidationError, match=r"missing acts_as, image"):
        Agent.model_validate({"name": "x", "mode": "browser"})
    with pytest.raises(ValidationError, match="exactly one of role or person"):
        Agent.model_validate({"name": "x", "mode": "remote", "acts_as": {}})


SCENARIO: dict[str, Any] = {
    "id": "rotate-leaked-token",
    "kind": "functional",
    "title": "Remove a committed credential and rotate it",
    "acts_as": {"role": "engineer"},
    "overlay": [{"gitea.commit": {"repo": "billing-service", "path": "config/settings.py"}}],
    "delivery": {
        "channel": "gitea.issue_assigned",
        "repo": "billing-service",
        "from": {"role": "manager"},
        "title": "Token committed in settings.py",
    },
    "checks": {
        "success": [{"gitea.file_not_contains": {"repo": "billing-service"}}],
        "forbidden": [{"mattermost.message_contains": {"text": "x"}}],
        "side_effects": {"allow": [{"gitea": {"repo": "billing-service"}}]},
    },
    "limits": {"max_minutes": 20, "done_when": "issue_closed_or_idle"},
}


def test_scenario_from_spec() -> None:
    s = Scenario.model_validate(SCENARIO)
    assert s.delivery.sender is not None
    assert s.delivery.sender.role == "manager"


def test_scenario_rejects_bad_operation_name() -> None:
    bad = {**SCENARIO, "overlay": [{"commit": {}}]}
    with pytest.raises(ValidationError, match=r"product\.operation"):
        Scenario.model_validate(bad)


def test_event_type_must_match_source() -> None:
    base: dict[str, Any] = {"seq": 1, "ts": datetime(2026, 11, 20, tzinfo=UTC), "run_id": "r_8f3k2"}
    Event.model_validate({**base, "source": "gateway", "type": "http.exchange"})
    Event.model_validate({**base, "source": "mcp", "type": "mcp.call", "org": None})
    with pytest.raises(ValidationError, match="is not a dns event"):
        Event.model_validate({**base, "source": "dns", "type": "http.exchange"})
    with pytest.raises(ValidationError, match="UTC"):
        Event.model_validate(
            {
                **base,
                "ts": datetime(2026, 11, 20, tzinfo=timezone(timedelta(hours=2))),
                "source": "dns",
                "type": "dns.query",
            }
        )


def test_org_and_user_are_optional_everywhere() -> None:
    for model in (Event, Result):
        assert model.model_fields["org"].default is None
        assert model.model_fields["user"].default is None


def test_every_schema_generates() -> None:
    for name, model in SCHEMAS.items():
        schema = model.model_json_schema()
        assert schema["type"] == "object", name
