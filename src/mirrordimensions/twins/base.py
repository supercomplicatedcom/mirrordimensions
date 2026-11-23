# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""What every twin adapter provides, and what it is given."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from mirrordimensions.engine.docker_api import ContainerSpec, Docker
from mirrordimensions.twins.relay import Relay


@dataclass
class TwinContext:
    """Everything an adapter needs about one app in one world."""

    app_id: str
    hostname: str
    company: str
    seed: int
    app_container: str
    app_ip: str
    db_container: str
    db_ip: str
    network: str
    dns: list[str]
    secrets: dict[str, str]
    settings: dict[str, Any] = field(default_factory=dict[str, Any])

    @property
    def volume_prefix(self) -> str:
        return f"{self.app_id}-"


@dataclass
class Identity:
    """Credentials in the form a production deployment uses. Opaque to the runner."""

    username: str
    password: str
    token: str
    env: dict[str, str]


class Twin(Protocol):
    product: str
    upstream_port: int
    static_path: str  # a file served identically every time, for the transparency check

    def containers(self, ctx: TwinContext) -> list[ContainerSpec]: ...
    def volumes(self, ctx: TwinContext) -> list[str]: ...
    def wait_ready(self, relay: Relay, ctx: TwinContext, timeout_s: float) -> None: ...
    def bootstrap(self, docker: Docker, relay: Relay, ctx: TwinContext) -> None: ...
    def issue_identity(
        self,
        relay: Relay,
        ctx: TwinContext,
        username: str,
        full_name: str,
        email: str,
        grants: dict[str, Any],
    ) -> Identity: ...
    def dump_state(self, relay: Relay, ctx: TwinContext) -> dict[str, Any]: ...


def get_twin(product: str | None) -> Twin | None:
    """The adapter for a product, or None if no twin exists yet (a stub stands in)."""
    if product == "gitea":
        from mirrordimensions.twins.gitea.adapter import Gitea

        return Gitea()
    if product == "mattermost":
        from mirrordimensions.twins.mattermost.adapter import Mattermost

        return Mattermost()
    return None
