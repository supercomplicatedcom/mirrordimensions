# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""What every twin adapter provides, and what it is given."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, Protocol

from mirrordimensions.engine.docker_api import ContainerSpec, Docker
from mirrordimensions.twins.relay import Relay

if TYPE_CHECKING:
    from mirrordimensions.world.model import Person, World


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
    gateway_ip: str = "10.41.0.10"

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


@dataclass
class RunContext:
    """What a scenario operation is given: the twin, the world, who the agent acts as, and
    the facts earlier operations recorded (an issue number the delivery created, say)."""

    docker: Docker
    relay: Relay
    ctx: TwinContext
    world: World
    acts_as: Person
    person: Callable[[dict[str, Any]], Person]  # {role, not: acts_as} or {person} -> Person
    facts: dict[str, Any] = field(default_factory=dict[str, Any])
    people: Callable[[dict[str, Any]], list[Person]] | None = None  # every match, in order
    now: datetime | None = None


@dataclass
class CheckOutcome:
    passed: bool
    evidence: str


# One scenario operation: (context, arguments) -> result.
Overlay = Callable[[RunContext, dict[str, Any]], None]
Delivery = Callable[[RunContext, dict[str, Any]], dict[str, Any]]  # returns what was delivered
StateCheck = Callable[[RunContext, dict[str, Any]], CheckOutcome]


@dataclass
class Operations:
    """A twin's scenario vocabulary (build spec, "Scenario file"): named overlay steps,
    delivery channels and final-state checks. Names are used without the product prefix."""

    overlays: dict[str, Overlay] = field(default_factory=dict[str, Overlay])
    deliveries: dict[str, Delivery] = field(default_factory=dict[str, Delivery])
    checks: dict[str, StateCheck] = field(default_factory=dict[str, StateCheck])


@dataclass(frozen=True)
class StateObject:
    """One object in a state dump: what it is, where it lives, and its value."""

    key: str  # stable, e.g. "repo:northfield/billing-service/file:config/settings.py"
    scope: dict[str, str]  # matched by side_effects.allow, e.g. {"repo": "billing-service"}
    value: Any


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
    def seed(
        self, docker: Docker, relay: Relay, ctx: TwinContext, world: World, now: datetime
    ) -> dict[str, int]:
        """Load the company into the product, backdated, and remove seeding's own traces."""
        ...

    def setup_traces(self, docker: Docker, relay: Relay, ctx: TwinContext) -> list[str]:
        """What building the world left behind that a real company would not have; empty when clean."""
        ...

    def operations(self) -> Operations:
        """Overlays, deliveries and checks this twin adds to the scenario vocabulary."""
        ...

    def state_objects(self, dump: dict[str, Any]) -> list[StateObject]:
        """A state dump as individual objects, for the per-object side-effect comparison."""
        ...


def get_twin(product: str | None) -> Twin | None:
    """The adapter for a product, or None if no twin exists yet (a stub stands in)."""
    if product == "gitea":
        from mirrordimensions.twins.gitea.adapter import Gitea

        return Gitea()
    if product == "mattermost":
        from mirrordimensions.twins.mattermost.adapter import Mattermost

        return Mattermost()
    return None
