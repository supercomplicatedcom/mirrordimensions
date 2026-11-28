# SPDX-License-Identifier: Apache-2.0
"""The device platform: a building-access REST service fronting the world's devices
(decision 0026). Its software is this repository's own `server.py` and the device
simulator, both standard library only, run in an image the engine already has.

Access is per site: `viewer` reads, `operator` also commands ordinary devices, `security`
also commands restricted ones. State lives in the running service; restoring the base
snapshot restarts it, so every run starts from the same devices at time zero.
"""

# JSON from the platform and its configuration is untyped.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownLambdaType=false

from __future__ import annotations

import json
from datetime import datetime
from importlib.resources import files
from typing import TYPE_CHECKING, Any

from mirrordimensions.devices.state import device_config, dump_from, state_objects
from mirrordimensions.engine.docker_api import ContainerSpec, Docker
from mirrordimensions.errors import MirrorError
from mirrordimensions.twins.base import Identity, Operations, StateObject, TwinContext
from mirrordimensions.twins.profile import ProfileMethods
from mirrordimensions.twins.relay import Relay

if TYPE_CHECKING:
    from mirrordimensions.world.model import World

PORT = 8080
SERVER = "/opt/platform/server.py"
SIM = "/opt/platform/sim.py"
CONFIG = "/etc/platform/config.json"


def platform_config(ctx: TwinContext) -> dict[str, Any]:
    """What the service is given: the shared device configuration, and its admin token."""
    return {**device_config(ctx), "admin_token": ctx.secrets.get("internal_token", "")}


class DevicePlatform(ProfileMethods):
    product = "device-platform"
    grant_key: str = "sites"
    grant_levels: tuple[str, ...] = ("viewer", "operator", "security")
    upstream_port = PORT
    static_path = "/healthz"

    def _base(self, ctx: TwinContext) -> str:
        return f"http://{ctx.app_ip}:{PORT}"

    def _admin(self, ctx: TwinContext) -> dict[str, str]:
        return {"Authorization": f"Bearer {ctx.secrets['internal_token']}"}

    def volumes(self, ctx: TwinContext) -> list[str]:
        return []  # state is in the running service; a restart is a reset

    def containers(self, ctx: TwinContext) -> list[ContainerSpec]:
        from mirrordimensions.network.sandbox import IMAGES  # an image with Python 3

        server = files("mirrordimensions.twins.device_platform").joinpath("server.py").read_bytes()
        sim = files("mirrordimensions.devices.world").joinpath("sim.py").read_bytes()
        return [
            ContainerSpec(
                name=ctx.app_container,
                image=IMAGES["gateway"],
                networks={ctx.network: ctx.app_ip},
                dns=ctx.dns,
                entrypoint=["python3", "-u", SERVER],
                command=[],
                user="65534:65534",
                files={
                    SERVER: (server, 0o644),
                    SIM: (sim, 0o644),
                    CONFIG: (json.dumps(platform_config(ctx)).encode(), 0o644),
                },
            )
        ]

    def wait_ready(self, relay: Relay, ctx: TwinContext, timeout_s: float) -> None:
        relay.wait_for(f"{self._base(ctx)}/healthz", timeout_s)

    def bootstrap(self, docker: Docker, relay: Relay, ctx: TwinContext) -> None:
        return None  # configured entirely by its file

    def issue_identity(
        self,
        relay: Relay,
        ctx: TwinContext,
        username: str,
        full_name: str,
        email: str,
        grants: dict[str, Any],
    ) -> Identity:
        sites = dict(grants.get(self.grant_key) or {})
        resp = relay.request(
            "POST",
            f"{self._base(ctx)}/api/v1/admin/users",
            body={"username": username, "name": full_name, "email": email, "sites": sites},
            headers=self._admin(ctx),
        )
        if resp.status != 201:
            raise MirrorError(
                f"The device platform did not issue an account for {username}.",
                f"It answered {resp.status}.",
                "Check that the sandbox is up: mirror status",
            )
        token = str(resp.json()["token"])
        prefix = ctx.app_id.upper().replace("-", "_")
        return Identity(
            username=username,
            password="",
            token=token,
            env={f"{prefix}_URL": f"https://{ctx.hostname}", f"{prefix}_TOKEN": token},
        )

    def export(self, relay: Relay, ctx: TwinContext) -> dict[str, Any]:
        """The service's own account: time, every device's state, every command attempted."""
        resp = relay.request(
            "GET", f"{self._base(ctx)}/api/v1/admin/export", headers=self._admin(ctx)
        )
        if resp.status != 200:
            raise MirrorError(
                "The device platform's state could not be read.",
                f"It answered {resp.status}.",
                "Check that the sandbox is up: mirror status",
            )
        data: dict[str, Any] = resp.json()
        return data

    def reconcile(
        self, relay: Relay, ctx: TwinContext, events: list[dict[str, Any]]
    ) -> tuple[int, list[str]]:
        """Its commands came through the gateway, and its devices are in the state they
        produce (decision 0026)."""
        from mirrordimensions.devices import reconcile

        export = self.export(relay, ctx)
        problems = reconcile.account_collected(events, ctx.app_id, export)
        problems += reconcile.commands_against_requests(events, ctx.hostname, ctx.app_id)
        problems += reconcile.state_against_commands(
            events, ctx.app_id, platform_config(ctx), export
        )
        return len(export["commands"]), problems

    def dump_state(self, relay: Relay, ctx: TwinContext) -> dict[str, Any]:
        return dump_from(ctx, self.export(relay, ctx))

    def seed(
        self, docker: Docker, relay: Relay, ctx: TwinContext, world: World, now: datetime
    ) -> dict[str, int]:
        return {"devices": len(ctx.devices)}

    def setup_traces(self, docker: Docker, relay: Relay, ctx: TwinContext) -> list[str]:
        data = self.export(relay, ctx)
        return ["commands sent while the world was built"] if data["commands"] else []

    def operations(self) -> Operations:
        from mirrordimensions.twins.device_platform.ops import operations

        return operations()

    def state_objects(self, dump: dict[str, Any]) -> list[StateObject]:
        return state_objects(dump)

    def account_source(self, ctx: TwinContext) -> str:
        return ctx.app_container  # the service writes its own account of each command
