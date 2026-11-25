# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""The host engine driver: Docker Engine and gVisor directly on a Linux host (opt-in).

The operator installs and runs Docker and gVisor; setup checks them and names any fix.
The boundary is `host`: an escape from gVisor lands on the machine itself.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from mirrordimensions.engine.base import (
    DockerEndpoint,
    EgressEntry,
    EngineStatus,
    Resources,
    UpdateOutcome,
    egress_allow_commands,
)
from mirrordimensions.errors import MirrorError
from mirrordimensions.hostos.info import host_arch

SOCKET = Path("/var/run/docker.sock")


class HostEngine:
    name = "host"

    def setup(self, resources: Resources, on_step: object = None) -> EngineStatus:
        status = self.status()
        if status.state != "running":
            raise MirrorError(
                "Docker Engine is not running on this host.",
                f"No Docker socket answered at {SOCKET}.",
                "Install and start Docker Engine (not Docker Desktop), then: mirror engine setup",
            )
        if "runsc" not in status.versions:
            raise MirrorError(
                "gVisor is not registered with Docker.",
                "The Docker daemon lists no runsc runtime.",
                "Install gVisor and run: sudo runsc install && sudo systemctl restart docker",
            )
        return status

    def start(self, on_step: object = None) -> EngineStatus:
        return self.status()

    def stop(self) -> None:
        """The host's Docker is the operator's to stop."""

    def destroy(self) -> None:
        """Nothing was created on the host by setup."""

    def docker_endpoint(self) -> DockerEndpoint:
        return DockerEndpoint(url=f"unix://{SOCKET}")

    def update(self) -> UpdateOutcome:
        raise MirrorError(
            "The host engine has no guest of its own to update.",
            "It is Docker Engine on this Linux host, whose packages are yours to manage.",
            "Update the host with its package manager, with no run going.",
        )

    def set_egress_allow(self, entries: list[EgressEntry]) -> None:
        # Host mode runs the firewall on this machine; changing it needs passwordless sudo.
        for command in egress_allow_commands(entries):
            done = subprocess.run(
                ["sudo", "-n", *command], capture_output=True, text=True, check=False
            )
            if done.returncode != 0:
                raise MirrorError(
                    "This machine's firewall refused the model routes.",
                    (done.stderr or done.stdout).strip()[-300:],
                    "Allow passwordless sudo for nft, or use the engine VM (mirror engine setup).",
                )

    def clock_offset(self) -> float:
        return 0.0

    def status(self) -> EngineStatus:
        done = subprocess.run(
            [
                "docker",
                "-H",
                f"unix://{SOCKET}",
                "info",
                "--format",
                "{{json .Runtimes}}|{{.ServerVersion}}|{{.KernelVersion}}",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if done.returncode != 0:
            return EngineStatus(driver=self.name, state="absent", boundary="host")
        runtimes, version, kernel = [*done.stdout.strip().split("|"), "", "", ""][:3]
        versions = {"docker": version, "kernel": kernel}
        if '"runsc"' in runtimes:
            versions["runsc"] = "registered"
        arch = host_arch()
        return EngineStatus(
            driver=self.name,
            state="running",
            arch=arch if arch != "other" else None,
            boundary="host",
            versions=versions,
            clock_offset_s=0.0,
        )
