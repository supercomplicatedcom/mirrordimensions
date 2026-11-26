# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""Eclipse Mosquitto: the message broker devices publish to (decision 0026). Upstream image,
configured, never modified; used under BSD-3-Clause (it is `EPL-2.0 OR BSD-3-Clause`).

Two containers: the broker, and the devices on it (`devices/world/bus.py`, this repository's
standard-library code beside the simulator). Agents reach the broker only through the
gateway's MQTT listener on 8883, by its production name. Access is per site, as on the REST
platform: `viewer` reads every topic of the site; `operator` may also publish commands to
its ordinary devices; `security` to its restricted ones too. Accounts and access lists are
Mosquitto's own files, reloaded with SIGHUP as an administrator would.
"""

# JSON and container output are untyped.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

from __future__ import annotations

import json
import secrets
import time
from datetime import datetime
from importlib.resources import files
from typing import TYPE_CHECKING, Any

from mirrordimensions.devices.state import device_config, dump_from, state_objects
from mirrordimensions.devices.world.bus import EXPORT, topic_base
from mirrordimensions.engine.docker_api import ContainerSpec, Docker
from mirrordimensions.errors import MirrorError
from mirrordimensions.twins.base import Identity, Operations, StateObject, TwinContext
from mirrordimensions.twins.profile import ProfileMethods
from mirrordimensions.twins.relay import Relay

if TYPE_CHECKING:
    from mirrordimensions.world.model import World

IMAGE = "eclipse-mosquitto:2.1.4-alpine@sha256:fa12172a051310efe5bcb7a6a11b77bd5faacb82cbacd7742aa758bf024fd8e4"
PORT = 1883
CONF_DIR = "/mosquitto/config"
SEED_DIR = "/etc/mosquitto-seed"
USERS = f"{CONF_DIR}/users.json"  # who has which grants, from which the access list is made
BUS_USER = "facilities-controller"
RANKS = {"viewer": 1, "operator": 2, "security": 3}

CONFIG = """# Broker for the building's devices.
per_listener_settings false
listener 1883 0.0.0.0
allow_anonymous false
password_file /mosquitto/config/passwd
acl_file /mosquitto/config/acl
persistence false
log_dest stdout
log_type error
log_type warning
"""

# The config folder is the image's own (owned by mosquitto); the seeded files are copied in
# so the broker can hash and rewrite them, then it replaces this shell as process 1.
START = (
    f"cp {SEED_DIR}/mosquitto.conf {SEED_DIR}/passwd {SEED_DIR}/acl {SEED_DIR}/users.json {CONF_DIR}/ && "
    f"chmod 600 {CONF_DIR}/passwd {CONF_DIR}/acl && mosquitto_passwd -U {CONF_DIR}/passwd && "
    f"exec /usr/sbin/mosquitto -c {CONF_DIR}/mosquitto.conf"
)


def access_list(users: dict[str, dict[str, str]], devices: list[dict[str, Any]]) -> str:
    """Mosquitto's ACL: the devices' controller everywhere; each person by site and rank."""
    lines = [f"user {BUS_USER}", "topic readwrite #", ""]
    for username, sites in sorted(users.items()):
        lines.append(f"user {username}")
        for site, level in sorted(sites.items()):
            rank = RANKS.get(level, 0)
            if not rank:
                continue
            lines.append(f"topic read {site}/#")
            for d in devices:
                if d["at"].split("/")[0] != site:
                    continue
                needed = 3 if d.get("sensitivity") == "restricted" else 2
                if rank >= needed:
                    lines.append(f"topic write {topic_base(d)}/commands/#")
        lines.append("")
    return "\n".join(lines)


class Mosquitto(ProfileMethods):
    product = "mosquitto"
    grant_key: str = "sites"
    grant_levels: tuple[str, ...] = ("viewer", "operator", "security")
    upstream_port = PORT
    static_path = "/"

    def volumes(self, ctx: TwinContext) -> list[str]:
        return []  # nothing persists: a restart is a reset, as for the device platform

    def _bus_config(self, ctx: TwinContext) -> dict[str, Any]:
        return {
            **device_config(ctx),
            "broker": f"{ctx.app_ip}:{PORT}",
            "client_id": f"{BUS_USER}-{ctx.seed % 997:03d}",
            "username": BUS_USER,
            "password": ctx.secrets.get("internal_token", ""),
        }

    def containers(self, ctx: TwinContext) -> list[ContainerSpec]:
        from mirrordimensions.network.sandbox import IMAGES  # an image with Python 3

        world = files("mirrordimensions.devices.world")
        bus_files = {
            f"/opt/devices/{name}": (world.joinpath(name).read_bytes(), 0o644)
            for name in ("bus.py", "sim.py", "mqttwire.py")
        }
        seeds = {
            f"{SEED_DIR}/mosquitto.conf": (CONFIG.encode(), 0o644),
            f"{SEED_DIR}/passwd": (
                f"{BUS_USER}:{ctx.secrets.get('internal_token', '')}\n".encode(),
                0o644,
            ),
            f"{SEED_DIR}/acl": (access_list({}, ctx.devices).encode(), 0o644),
            f"{SEED_DIR}/users.json": (b"{}", 0o644),
        }
        return [
            ContainerSpec(
                name=ctx.app_container,
                image=IMAGE,
                networks={ctx.network: ctx.app_ip},
                dns=ctx.dns,
                entrypoint=["sh", "-c", START],
                command=[],
                user="1883:1883",
                files=seeds,
            ),
            ContainerSpec(
                name=ctx.db_container,
                image=IMAGES["gateway"],
                networks={ctx.network: ctx.db_ip},
                dns=ctx.dns,
                entrypoint=["python3", "-u", "/opt/devices/bus.py"],
                command=[],
                user="65534:65534",
                files={
                    **bus_files,
                    "/etc/devices/config.json": (json.dumps(self._bus_config(ctx)).encode(), 0o644),
                },
            ),
        ]

    def wait_ready(self, relay: Relay, ctx: TwinContext, timeout_s: float) -> None:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            up = relay.docker.exec(ctx.app_container, ["nc", "-z", "127.0.0.1", str(PORT)])
            if up.exit_code == 0 and relay.docker.read_file(ctx.db_container, EXPORT) is not None:
                return
            time.sleep(1)
        raise MirrorError(
            f"The message broker at {ctx.hostname} did not become ready.",
            "Either the broker or its devices did not start.",
            "Check: mirror status",
        )

    def bootstrap(self, docker: Docker, relay: Relay, ctx: TwinContext) -> None:
        return None

    def issue_identity(
        self,
        relay: Relay,
        ctx: TwinContext,
        username: str,
        full_name: str,
        email: str,
        grants: dict[str, Any],
    ) -> Identity:
        docker = relay.docker
        sites = {str(k): str(v) for k, v in dict(grants.get(self.grant_key) or {}).items()}
        current = docker.read_file(ctx.app_container, USERS)
        users: dict[str, dict[str, str]] = json.loads(current or b"{}")
        users[username] = sites
        password = secrets.token_urlsafe(24)
        steps = [
            ["mosquitto_passwd", "-b", f"{CONF_DIR}/passwd", username, password],
            ["sh", "-c", f'printf %s "$ACL" > {CONF_DIR}/acl && printf %s "$USERS" > {USERS}'],
            ["kill", "-HUP", "1"],  # the broker rereads its password and access files
        ]
        env = {"ACL": access_list(users, ctx.devices), "USERS": json.dumps(users)}
        for step in steps:
            out = docker.exec(ctx.app_container, step, env=env)
            if out.exit_code != 0:
                raise MirrorError(
                    f"The message broker did not issue an account for {username}.",
                    out.output.strip()[-200:],
                    "Check that the sandbox is up: mirror status",
                )
        prefix = ctx.app_id.upper().replace("-", "_")
        return Identity(
            username=username,
            password=password,
            token="",
            env={
                f"{prefix}_HOST": ctx.hostname,
                f"{prefix}_PORT": "8883",
                f"{prefix}_USERNAME": username,
                f"{prefix}_PASSWORD": password,
            },
        )

    def export(self, relay: Relay, ctx: TwinContext) -> dict[str, Any]:
        raw = relay.docker.read_file(ctx.db_container, EXPORT)
        if raw is None:
            raise MirrorError(
                "The devices on the message broker have not reported.",
                "",
                "Check that the sandbox is up: mirror status",
            )
        data: dict[str, Any] = json.loads(raw)
        return data

    def dump_state(self, relay: Relay, ctx: TwinContext) -> dict[str, Any]:
        return dump_from(ctx, self.export(relay, ctx))

    def reconcile(
        self, relay: Relay, ctx: TwinContext, events: list[dict[str, Any]]
    ) -> tuple[int, list[str]]:
        """Each command the devices carried out was published through the gateway, and the
        devices are in the state those commands produce."""
        from mirrordimensions.devices import reconcile

        export = self.export(relay, ctx)
        bases = {topic_base(d): d["id"] for d in ctx.devices}
        problems = reconcile.commands_against_publishes(events, ctx.hostname, ctx.app_id, bases)
        problems += reconcile.state_against_commands(events, ctx.app_id, device_config(ctx), export)
        return len(export["commands"]), problems

    def account_source(self, ctx: TwinContext) -> str:
        return ctx.db_container  # the devices write their own account of each command

    def seed(
        self, docker: Docker, relay: Relay, ctx: TwinContext, world: World, now: datetime
    ) -> dict[str, int]:
        return {"devices": len(ctx.devices)}

    def setup_traces(self, docker: Docker, relay: Relay, ctx: TwinContext) -> list[str]:
        commands = self.export(Relay(docker), ctx)["commands"]
        return ["commands sent while the world was built"] if commands else []

    def operations(self) -> Operations:
        from mirrordimensions.twins.device_platform.ops import operations

        return operations()

    def state_objects(self, dump: dict[str, Any]) -> list[StateObject]:
        return state_objects(dump)
