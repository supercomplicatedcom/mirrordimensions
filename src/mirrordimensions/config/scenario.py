# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""The scenario file.

Overlay steps and checks are named operations registered by twin adapters
(`gitea.commit`, `mattermost.message_posted`). Their arguments are checked against the
adapter's vocabulary once adapters exist (M2); here only their shape is checked.
"""

from __future__ import annotations

import re
from typing import Any, Literal, Self

from pydantic import ConfigDict, Field, model_validator

from mirrordimensions.config.agent import ActsAs
from mirrordimensions.config.common import Id, StrictModel

_OP = r"^[a-z][a-z0-9-]*\.[a-z][a-z0-9_]*$"


def _check_ops(entries: list[dict[str, Any]], where: str) -> None:
    for entry in entries:
        if len(entry) != 1:
            raise ValueError(f"each {where} entry names exactly one operation")
        (name,) = entry
        if not re.match(_OP, name):
            raise ValueError(f"{where} operation {name!r} must look like product.operation")


class PersonRef(StrictModel):
    """Someone in the world: by role or by person, optionally not the agent's own person."""

    role: str | None = None
    person: str | None = None
    not_: Literal["acts_as"] | None = Field(default=None, alias="not")

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    @model_validator(mode="after")
    def _one(self) -> Self:
        if (self.role is None) == (self.person is None):
            raise ValueError("give exactly one of role or person")
        return self


class Delivery(StrictModel):
    """How work reaches the agent. Fields beyond `channel` belong to the channel."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    channel: str = Field(pattern=_OP)
    sender: PersonRef | None = Field(default=None, alias="from")


class SideEffects(StrictModel):
    allow: list[dict[str, dict[str, Any]]] = Field(default_factory=list[dict[str, dict[str, Any]]])


class Checks(StrictModel):
    success: list[dict[str, Any]] = Field(default_factory=list[dict[str, Any]])
    forbidden: list[dict[str, Any]] = Field(default_factory=list[dict[str, Any]])
    side_effects: SideEffects = Field(default_factory=SideEffects)

    @model_validator(mode="after")
    def _ops(self) -> Self:
        _check_ops(self.success, "success check")
        _check_ops(self.forbidden, "forbidden check")
        return self


class Limits(StrictModel):
    max_minutes: int = Field(default=20, ge=1, le=240)
    done_when: Literal["process_exit", "idle", "issue_closed_or_idle"] = "idle"


class Scenario(StrictModel):
    id: Id
    kind: Literal["functional", "injection", "permission"]
    title: str = Field(min_length=3)
    acts_as: ActsAs
    overlay: list[dict[str, Any]] = Field(default_factory=list[dict[str, Any]])
    delivery: Delivery
    checks: Checks = Field(default_factory=Checks)
    limits: Limits = Field(default_factory=Limits)

    @model_validator(mode="after")
    def _ops(self) -> Self:
        _check_ops(self.overlay, "overlay")
        return self
