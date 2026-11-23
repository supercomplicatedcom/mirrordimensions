# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""The one wrapper around the Docker API. Nothing else talks to Docker directly.

It connects only to the engine's endpoint, never to the user's own Docker context.
"""

# The docker SDK is not fully typed.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportMissingTypeStubs=false

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import docker
from docker.errors import DockerException

from mirrordimensions.engine.base import DockerEndpoint
from mirrordimensions.errors import MirrorError


@dataclass
class RunOutput:
    exit_code: int
    output: str


class Docker:
    def __init__(self, endpoint: DockerEndpoint) -> None:
        try:
            self._client: Any = docker.DockerClient(base_url=endpoint.url, timeout=120)
            self._client.ping()
        except DockerException as exc:
            raise MirrorError(
                "Cannot reach the engine's Docker API.",
                str(exc),
                "Run: mirror engine start",
            ) from exc

    def info(self) -> dict[str, Any]:
        return dict(self._client.info())

    def runtimes(self) -> list[str]:
        return sorted(self.info().get("Runtimes", {}))

    def run(
        self,
        image: str,
        command: list[str],
        *,
        runtime: str | None = None,
        platform: str | None = None,
        network: str | None = None,
    ) -> RunOutput:
        """Run a short-lived container and return its exit code and combined output."""
        container: Any = self._client.containers.run(
            image,
            command,
            runtime=runtime,
            platform=platform,
            network=network,
            detach=True,
        )
        try:
            result = container.wait(timeout=300)
            output = container.logs(stdout=True, stderr=True).decode("utf-8", "replace")
            return RunOutput(exit_code=int(result.get("StatusCode", -1)), output=output)
        finally:
            container.remove(force=True)

    def pull(self, image: str, platform: str | None = None) -> None:
        self._client.images.pull(image, platform=platform)

    def create_network(self, name: str, *, internal: bool = False) -> dict[str, Any]:
        net: Any = self._client.networks.create(name, driver="bridge", internal=internal)
        net.reload()
        return dict(net.attrs)

    def remove_network(self, name: str) -> None:
        for net in self._client.networks.list(names=[name]):
            net.remove()
