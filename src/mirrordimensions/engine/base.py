# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""The contract every engine driver meets (plug-in group `mirrordimensions.engines`)."""

from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel


class Resources(BaseModel):
    cpus: int
    memory_gb: int
    disk_gb: int


class DockerEndpoint(BaseModel):
    url: str
    tls_dir: str | None = None


class EngineStatus(BaseModel):
    driver: str
    state: Literal["absent", "stopped", "running", "broken"]
    arch: Literal["arm64", "x64", "other"] | None = None
    boundary: Literal["dedicated-vm", "shared-vm", "host"] | None = None
    versions: dict[str, str] = {}
    resources: Resources | None = None
    clock_offset_s: float | None = None


class Engine(Protocol):
    name: str

    def setup(self, resources: Resources) -> EngineStatus: ...
    def start(self) -> EngineStatus: ...
    def stop(self) -> None: ...
    def status(self) -> EngineStatus: ...
    def destroy(self) -> None: ...
    def docker_endpoint(self) -> DockerEndpoint: ...
    def clock_offset(self) -> float: ...
