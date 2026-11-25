# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""The contract every engine driver meets (plug-in group `mirrordimensions.engines`)."""

from __future__ import annotations

from datetime import date
from typing import Literal, Protocol

from pydantic import BaseModel, Field


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


# Updates are installed when asked, never by themselves (provision.sh). After this many
# days without one, `mirror doctor` and `mirror engine status` say so.
UPDATE_DAYS = 14


class UpdateOutcome(BaseModel):
    upgraded: list[str] = Field(description="Packages updated, as `name version`")
    reboot_required: bool = Field(description="A new kernel or library waits for a restart")
    kernel: str = ""


def update_age_days(versions: dict[str, str], today: date) -> int | None:
    """Days since the engine's packages were last updated, from `versions["updated"]`."""
    try:
        return (today - date.fromisoformat(versions.get("updated", ""))).days
    except ValueError:
        return None


def update_note(versions: dict[str, str], today: date) -> str | None:
    """A sentence when the engine is due an update or a restart, else None."""
    age = update_age_days(versions, today)
    if versions.get("reboot") == "yes":
        return (
            "The engine installed updates that take effect when it restarts: "
            "mirror engine stop, then mirror engine start (with no run going)."
        )
    if age is not None and age > UPDATE_DAYS:
        return (
            f"The engine's packages were last updated {age} days ago. "
            "Bring the sandbox down and run: mirror engine update"
        )
    return None


EgressEntry = tuple[str, str, int]  # (source subnet, destination address, TCP port)


def egress_allow_commands(entries: list[EgressEntry]) -> list[list[str]]:
    """nft commands that make the edge's allow set exactly `entries`. Flushed first, so the
    set is never wider than asked; between the two commands it is empty (fails closed)."""
    commands = [["nft", "flush", "set", "inet", "edge", "egress_allow"]]
    if entries:
        elements = ", ".join(f"{src} . {dst} . {port}" for src, dst, port in sorted(set(entries)))
        commands.append(
            ["nft", "add", "element", "inet", "edge", "egress_allow", f"{{ {elements} }}"]
        )
    return commands


class Engine(Protocol):
    name: str

    def setup(self, resources: Resources) -> EngineStatus: ...
    def start(self) -> EngineStatus: ...
    def stop(self) -> None: ...
    def status(self) -> EngineStatus: ...
    def destroy(self) -> None: ...
    def docker_endpoint(self) -> DockerEndpoint: ...
    def clock_offset(self) -> float: ...
    def set_egress_allow(self, entries: list[EgressEntry]) -> None: ...
    def update(self) -> UpdateOutcome: ...
