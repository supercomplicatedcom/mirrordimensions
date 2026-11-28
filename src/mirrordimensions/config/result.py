# SPDX-License-Identifier: Apache-2.0
"""The run result, `result.json`.

The envelope (M0): status, isolation, the world it ran in, the host platform and the
plug-ins loaded. The run (M5): scenario and agent, what was delivered, every check with its
evidence, unexpected side effects per object, where canaries travelled, suspicion flags, and
coverage. Nothing here depends on wall-clock time, so two runs of a scripted agent give the
same result apart from `run_id`.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from mirrordimensions.config.common import StrictModel
from mirrordimensions.hostos.info import Arch, HostOS


class PluginRef(StrictModel):
    group: str
    name: str
    target: str = Field(description="module:attribute the entry point names")
    distribution: str | None = None
    version: str | None = None


class Platform(StrictModel):
    host_os: HostOS
    host_os_version: str
    host_arch: Arch
    engine_driver: Literal["lima", "wsl", "host"] | None = None
    engine_arch: Arch | None = None
    guest_kernel: str | None = None
    engine_updated: str | None = Field(
        default=None, description="When the engine's packages were last updated (YYYY-MM-DD)"
    )
    docker_version: str | None = None
    runsc_version: str | None = None
    boundary: Literal["dedicated-vm", "shared-vm", "host", "remote"] | None = None
    emulated: list[str] = Field(default_factory=list[str])


class WorldRef(StrictModel):
    name: str
    seed: int
    definition_hash: str


class Result(StrictModel):
    run_id: str = Field(pattern=r"^r_[a-z0-9]{4,32}$")
    status: Literal["passed", "failed", "errored", "stopped"]
    isolation: Literal["full", "reduced", "failed", "remote"]
    world: WorldRef
    platform: Platform
    plugins: list[PluginRef] = Field(default_factory=list[PluginRef])
    checks: list[dict[str, Any]] = Field(default_factory=list[dict[str, Any]])
    component_versions: dict[str, str] = Field(default_factory=dict[str, str])
    scenario: str | None = None
    agent: str | None = None
    acts_as: str | None = None
    reason: str | None = Field(default=None, description="Why a run stopped or errored")
    isolation_reason: str | None = None
    delivery: dict[str, Any] = Field(default_factory=dict[str, Any])
    side_effects: list[dict[str, Any]] = Field(
        default_factory=list[dict[str, Any]], description="Unexpected changes, one per object"
    )
    allowed_changes: int = 0
    physical: list[dict[str, Any]] = Field(
        default_factory=list[dict[str, Any]],
        description="Physical consequences: each disruptive or safety-critical device command"
        " tried, what it would cause, whether the job called for it and whether the agent asked"
        " first",
    )
    canaries: list[dict[str, Any]] = Field(default_factory=list[dict[str, Any]])
    egress: list[dict[str, Any]] = Field(
        default_factory=list[dict[str, Any]],
        description="The agent's attempts to reach outside the world: refused connections and"
        " failed lookups",
    )
    suspected: bool = False
    suspicion: list[dict[str, Any]] = Field(default_factory=list[dict[str, Any]])
    coverage: dict[str, Any] = Field(default_factory=dict[str, Any])
    access: dict[str, Any] = Field(
        default_factory=dict[str, Any],
        description="Hosts, repositories, channels and tools touched against those granted",
    )
    org: str | None = Field(default=None, description="Empty when self-hosted")
    user: str | None = Field(default=None, description="Empty when self-hosted")
