# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""The agent file, `agents/<name>.yaml`."""

from __future__ import annotations

from typing import Any, Literal, Self

from pydantic import Field, model_validator

from mirrordimensions.config.common import EnvName, Id, StrictModel


class ActsAs(StrictModel):
    role: str | None = None
    person: str | None = None

    @model_validator(mode="after")
    def _one(self) -> Self:
        if (self.role is None) == (self.person is None):
            raise ValueError("give exactly one of role or person")
        return self


class Wake(StrictModel):
    type: Literal["command", "poll"]
    command: list[str] | None = None

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.type == "command" and not self.command:
            raise ValueError("wake type command needs a command")
        return self


class Agent(StrictModel):
    name: Id
    mode: Literal["hosted", "browser", "remote"]
    status: Literal["draft"] | None = Field(
        default=None, description="Set while onboarding is unfinished"
    )
    step: int | None = Field(
        default=None, ge=1, le=6, description="Onboarding step reached, for drafts"
    )
    acts_as: ActsAs | None = None
    image: str | None = Field(default=None, description="Container image; hosted and browser modes")
    build: str | None = Field(
        default=None,
        description="Folder with a Dockerfile, relative to the agent file; built into `image`",
    )
    production_arch: Literal["amd64", "arm64"] | None = None
    model: Id | None = Field(
        default=None, description="The model route in mirror.yaml it calls; omitted when none"
    )
    wake: Wake | None = None
    env: dict[EnvName, str] = Field(default_factory=dict[str, str])
    grants: dict[Id, dict[str, Any]] = Field(default_factory=dict[str, dict[str, Any]])

    @model_validator(mode="after")
    def _complete(self) -> Self:
        if self.status == "draft":
            return self
        missing: list[str] = []
        if self.acts_as is None:
            missing.append("acts_as")
        if self.mode in ("hosted", "browser") and not self.image:
            missing.append("image")
        if self.mode == "hosted" and self.wake is None:
            missing.append("wake")
        if self.mode == "remote" and self.image:
            raise ValueError("a remote agent runs on its vendor's platform and has no image")
        if missing:
            raise ValueError(
                f"missing {', '.join(missing)} (or mark the file status: draft while onboarding)"
            )
        return self
