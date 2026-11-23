# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""The run result, `result.json`.

M0 defines the envelope: status, isolation, the world it ran in, the host platform and the
plug-ins that were loaded. Checks, coverage and the ledger fill in from M5.
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
    org: str | None = Field(default=None, description="Empty when self-hosted")
    user: str | None = Field(default=None, description="Empty when self-hosted")
