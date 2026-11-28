# SPDX-License-Identifier: Apache-2.0
"""Scenarios, built-in and the project's own: `mirror scenario list|show` and the portal's
Scenarios screen."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from mirrordimensions.config.scenario import Scenario
from mirrordimensions.errors import MirrorError
from mirrordimensions.project import Project
from mirrordimensions.runner import scenario as scenario_mod

CHANNEL_WORDS = {
    "gitea.issue_assigned": "an assigned issue",
    "mattermost.message": "a chat message",
    "mattermost.direct_message": "a direct message",
}


class ScenarioSummary(BaseModel):
    id: str
    kind: Literal["functional", "injection", "permission"]
    title: str
    source: Literal["built-in", "project"]
    delivery: str
    delivery_words: str
    acts_as: str
    systems: list[str]
    suites: list[str] = Field(default_factory=list[str])
    mcp_tools: list[str] = Field(default_factory=list[str])
    max_minutes: int


def _systems(s: Scenario) -> list[str]:
    """The products a scenario uses, from its operation names (`gitea.commit`)."""
    names: set[str] = {str(k).split(".", 1)[0] for step in s.overlay for k in step}
    for entry in [*s.checks.success, *s.checks.forbidden]:
        names |= {str(k).split(".", 1)[0] for k in entry}
    names.add(s.delivery.channel.split(".", 1)[0])
    return sorted(names)


def list_scenarios(project: Project) -> list[ScenarioSummary]:
    builtin = scenario_mod.builtin()
    found = scenario_mod.available(project.root / "scenarios")
    out: list[ScenarioSummary] = []
    for sid in sorted(found):
        s = found[sid]
        acts = s.acts_as.role or s.acts_as.person or ""
        out.append(
            ScenarioSummary(
                id=s.id,
                kind=s.kind,
                title=s.title,
                source="built-in" if sid in builtin and builtin[sid] == s else "project",
                delivery=s.delivery.channel,
                delivery_words=CHANNEL_WORDS.get(s.delivery.channel, s.delivery.channel),
                acts_as=acts,
                systems=_systems(s),
                suites=[name for name, ids in scenario_mod.SUITES.items() if sid in ids],
                mcp_tools=list(s.mcp.tools) if s.mcp else [],
                max_minutes=s.limits.max_minutes,
            )
        )
    return out


def show_scenario(project: Project, scenario_id: str) -> dict[str, Any]:
    found = scenario_mod.available(project.root / "scenarios")
    if scenario_id not in found:
        raise MirrorError(
            f"There is no scenario called {scenario_id!r}.",
            f"Scenarios: {', '.join(sorted(found))}.",
            "List them with: mirror scenario list",
        )
    return found[scenario_id].model_dump(by_alias=True, exclude_none=True, mode="json")
