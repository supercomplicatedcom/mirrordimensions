# SPDX-License-Identifier: Apache-2.0
"""What every twin adapter provides, and what it is given."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from mirrordimensions.engine.docker_api import ContainerSpec, Docker
from mirrordimensions.twins.relay import Relay

if TYPE_CHECKING:
    from mirrordimensions.twins.profile import ResourceRef
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
    # A device platform's world: every site, and the devices this platform fronts.
    sites: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    devices: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    # The people the building knows: badges and hours (`devices/people.py`).
    people: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])

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
# What the agent must be granted to see work delivered this way: grant key -> names, such
# as {"repos": ["billing-service"]}. Grants are exact, so work elsewhere could not be read.
DeliveryNeeds = Callable[[dict[str, Any]], dict[str, list[str]]]
# A check over what the agent did, as captured: (context, arguments, the agent's exchanges)
# -> outcome; `passed` means "found" for forbidden use. Each exchange is an `http.exchange`
# event with its `seq`.
EventCheck = Callable[[RunContext, dict[str, Any], list[dict[str, Any]]], CheckOutcome]


@dataclass
class Operations:
    """A twin's scenario vocabulary (build spec, "Scenario file"): named overlay steps,
    delivery channels and final-state checks. Names are used without the product prefix."""

    overlays: dict[str, Overlay] = field(default_factory=dict[str, Overlay])
    deliveries: dict[str, Delivery] = field(default_factory=dict[str, Delivery])
    delivery_needs: dict[str, DeliveryNeeds] = field(default_factory=dict[str, DeliveryNeeds])
    checks: dict[str, StateCheck] = field(default_factory=dict[str, StateCheck])
    event_checks: dict[str, EventCheck] = field(default_factory=dict[str, EventCheck])


@dataclass(frozen=True)
class StateObject:
    """One object in a state dump: what it is, where it lives, and its value."""

    key: str  # stable, e.g. "repo:northfield/billing-service/file:config/settings.py"
    scope: dict[str, str]  # matched by side_effects.allow, e.g. {"repo": "billing-service"}
    value: Any


class Twin(Protocol):
    product: str
    grant_key: str  # the key an agent file's grants use for this product
    grant_levels: tuple[str, ...]  # the levels it accepts; one level means "member" or not
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

    def locate(self, exchange: dict[str, Any]) -> ResourceRef | None:
        """The surface and resource an exchange acted on (generated from the profile)."""
        ...

    def describe(self, exchange: dict[str, Any]) -> str:
        """What the exchange did, in a few plain words ("Reads config/settings.py")."""
        ...


@runtime_checkable
class Reconciles(Protocol):
    """A twin that keeps its own account of what was done to it, which the run's coverage
    checks against what the gateway captured (the device platform, decision 0026)."""

    def reconcile(
        self, relay: Relay, ctx: TwinContext, events: list[dict[str, Any]]
    ) -> tuple[int, list[str]]:
        """How many actions it recorded, and each one nothing captured explains."""
        ...

    def account_source(self, ctx: TwinContext) -> str:
        """The container whose log is that account, collected during a run."""
        ...


# Scenario operations named for what they act on rather than the product: `device.state_is`
# and `site.no_unlocked_door_at_end` are the device platform's (decision 0026).
DEVICES = "device-platform"  # the operations' home; they span every system with devices
OPERATION_PREFIXES = {"device": DEVICES, "site": DEVICES}


def product_of(operation: str) -> str:
    """The product a scenario operation (`<prefix>.<name>`) belongs to."""
    prefix = operation.partition(".")[0]
    return OPERATION_PREFIXES.get(prefix, prefix)


def get_twin(product: str | None) -> Twin | None:
    """The adapter for a product, or None if no twin exists yet (a stub stands in)."""
    if product == "gitea":
        from mirrordimensions.twins.gitea.adapter import Gitea

        return Gitea()
    if product == "mattermost":
        from mirrordimensions.twins.mattermost.adapter import Mattermost

        return Mattermost()
    if product == "mosquitto":
        from mirrordimensions.twins.mosquitto.adapter import Mosquitto

        return Mosquitto()
    if product == "device-platform":
        from mirrordimensions.twins.device_platform.adapter import DevicePlatform

        return DevicePlatform()
    return None
