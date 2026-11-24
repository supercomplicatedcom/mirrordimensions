# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""The wsl engine driver: a dedicated WSL2 distribution on Windows 11.

EXPERIMENTAL: built to the spec and unit-tested, but not yet verified on real hardware
(decision 0006, docs/platforms/windows-verification.md). Setup refuses to run unless the
caller passes `experimental=True`.
"""

from __future__ import annotations

import subprocess
from importlib.resources import files

from mirrordimensions.engine.base import (
    DockerEndpoint,
    EgressEntry,
    EngineStatus,
    Resources,
    egress_allow_commands,
)
from mirrordimensions.errors import MirrorError
from mirrordimensions.hostos.dirs import data_dir

DISTRIBUTION = "engine"
DOCKER_PORT = 23760

WSL_CONF = """\
# Written by mirror engine setup. Nothing from Windows is shared with the engine.
[automount]
enabled = false
mountFsTab = false

[interop]
enabled = false
appendWindowsPath = false

[boot]
systemd = true

[network]
generateHosts = false
"""


def provision_script() -> str:
    script = files("mirrordimensions.engine.provision").joinpath("provision.sh").read_text("utf-8")
    # No forwarded socket in WSL: Docker listens on loopback with mutual TLS (decision 0003).
    return script.replace("__ENGINE_USER__", "")


def docker_tls_dropin(port: int = DOCKER_PORT) -> str:
    """systemd drop-in: Docker on the engine's loopback only, mutual TLS required."""
    return (
        "[Service]\n"
        "ExecStart=\n"
        "ExecStart=/usr/bin/dockerd -H fd:// "
        f"-H tcp://127.0.0.1:{port} --tlsverify "
        "--tlscacert=/etc/docker/tls/ca.pem --tlscert=/etc/docker/tls/server.pem "
        "--tlskey=/etc/docker/tls/server-key.pem\n"
    )


class WslEngine:
    name = "wsl"

    def __init__(self) -> None:
        self.root = data_dir()
        self.tls_dir = self.root / "docker-tls"

    def setup(
        self, resources: Resources, on_step: object = None, experimental: bool = False
    ) -> EngineStatus:
        if not experimental:
            raise MirrorError(
                "The Windows engine is experimental.",
                "It is not yet verified on real hardware (docs/platforms/windows-verification.md).",
                "To try it anyway: mirror engine setup --experimental",
            )
        raise MirrorError(
            "The Windows engine cannot be created yet.",
            "Importing the WSL distribution is written but untested, so it is switched off.",
            "Track progress in docs/platforms/windows-verification.md.",
        )

    def start(self, on_step: object = None) -> EngineStatus:
        return self.status()

    def stop(self) -> None:
        subprocess.run(["wsl", "--terminate", DISTRIBUTION], capture_output=True, check=False)

    def destroy(self) -> None:
        subprocess.run(["wsl", "--unregister", DISTRIBUTION], capture_output=True, check=False)

    def docker_endpoint(self) -> DockerEndpoint:
        return DockerEndpoint(url=f"tcp://127.0.0.1:{DOCKER_PORT}", tls_dir=str(self.tls_dir))

    def set_egress_allow(self, entries: list[EgressEntry]) -> None:
        for command in egress_allow_commands(entries):
            done = subprocess.run(
                ["wsl", "-d", DISTRIBUTION, "-u", "root", "--", *command],
                capture_output=True,
                text=True,
                check=False,
            )
            if done.returncode != 0:
                raise MirrorError(
                    "The engine's firewall refused the model routes.",
                    (done.stderr or done.stdout).strip()[-300:],
                    "Run: mirror engine setup (it reinstalls the firewall), then try again.",
                )

    def clock_offset(self) -> float:
        return 0.0

    def status(self) -> EngineStatus:
        try:
            done = subprocess.run(["wsl", "--list", "--quiet"], capture_output=True, check=False)
        except OSError:
            return EngineStatus(driver=self.name, state="absent", boundary="shared-vm")
        names = done.stdout.decode("utf-16-le", "ignore").split()
        state = "stopped" if DISTRIBUTION in names else "absent"
        return EngineStatus(
            driver=self.name, state=state, boundary="shared-vm", versions={"status": "experimental"}
        )
