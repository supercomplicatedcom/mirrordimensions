# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""Exposing a world's MCP server to a remote agent (decisions 0009 and 0024).

`mirror world expose` records the public hostname in mirror.yaml, brings up the ingress
(a sandbox restart), issues the remote agent's identity (its person signs in on the
company's page), prints the reverse-proxy settings, and relays connections from 127.0.0.1
into the ingress until stopped. Nothing is reachable from outside while it is not running.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field

from mirrordimensions.errors import MirrorError
from mirrordimensions.project import Project
from mirrordimensions.service import agents as agents_svc
from mirrordimensions.service.changes import Change
from mirrordimensions.world.denylist import findings

DEFAULT_PORT = 7480


class Exposure(BaseModel):
    app_id: str
    agent: str
    public_url: str = Field(description="What the vendor platform is given, as a connector URL")
    local: str = Field(description="Where the reverse proxy sends requests: the relay")
    username: str = Field(description="The person who signs in on the company's page")
    password: str
    caddy: str
    nginx: str


def _quiet(_text: str) -> None:
    return None


def check_hostname(hostname: str) -> None:
    """A public hostname the agent will see: no name that gives the test away."""
    problems = findings(hostname)
    if problems:
        raise MirrorError(
            f"{hostname} cannot be used: it contains {', '.join(sorted(set(problems)))}.",
            "The agent's platform sees this name; nothing it sees may reveal a test.",
            "Choose a name under a domain your company would use, such as tools.<your-domain>.",
        )


def proxy_settings(hostname: str, port: int) -> tuple[str, str]:
    """Caddy and nginx settings for the owner's reverse proxy, which holds the certificate."""
    caddy = (
        f"{hostname} {{\n"
        f"    reverse_proxy 127.0.0.1:{port} {{\n"
        "        flush_interval -1\n"
        "    }\n"
        "}\n"
    )
    nginx = (
        "server {\n"
        "    listen 443 ssl;\n"
        f"    server_name {hostname};\n"
        f"    ssl_certificate     /etc/ssl/{hostname}/fullchain.pem;\n"
        f"    ssl_certificate_key /etc/ssl/{hostname}/privkey.pem;\n"
        "    location / {\n"
        f"        proxy_pass http://127.0.0.1:{port};\n"
        "        proxy_set_header Host $host;\n"
        "        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n"
        "        proxy_set_header X-Forwarded-Proto https;\n"
        "        proxy_http_version 1.1;\n"
        "        proxy_buffering off;\n"
        "        proxy_read_timeout 1h;\n"
        "    }\n"
        "}\n"
    )
    return caddy, nginx


def expose(
    project: Project,
    app_id: str,
    hostname: str,
    agent_name: str,
    *,
    port: int = DEFAULT_PORT,
    on_step: Callable[[str], None] | None = None,
) -> Exposure:
    """Expose an MCP server at a public hostname for one remote agent, and bring the
    ingress up. The relay is started separately (`relay`), since it runs until stopped."""
    from mirrordimensions.service import environment as env_svc
    from mirrordimensions.service.systems import edit_manifest

    say = on_step or _quiet
    hostname = hostname.strip().lower().rstrip(".")
    check_hostname(hostname)
    manifest = agents_svc._manifest(project)  # pyright: ignore[reportPrivateUsage]
    app = next((a for a in manifest.apps if a.id == app_id), None)
    if app is None or app.kind != "mcp-server" or app.serves is None:
        raise MirrorError(
            f"{app_id} is not one of this world's MCP servers.",
            "Only an MCP server the world serves can be exposed to a remote agent.",
            "Run: mirror system list",
        )
    if app.visibility == "absent":
        raise MirrorError(
            f"{app_id} is absent from this world.",
            "",
            f"Run: mirror set visibility {app_id} granted",
        )
    if any(a.hostname.lower() == hostname for a in manifest.apps):
        raise MirrorError(
            f"{hostname} already names a system inside the world.",
            "The public hostname is the one the vendor platform reaches from outside.",
            "Choose a name your reverse proxy serves, such as tools.<your-domain>.",
        )
    agent, _ = agents_svc.load_agent(project, agent_name)
    if agent.mode != "remote":
        raise MirrorError(
            f"{agent_name} is a {agent.mode} agent.",
            "Only a remote agent, which runs on its vendor's platform, comes in from outside.",
            "Onboard it as a remote agent: mirror agent new --mode remote",
        )
    if app_id not in agent.grants:
        raise MirrorError(
            f"{agent_name} is not granted {app_id}.",
            "A remote agent works only through the MCP server it is granted.",
            f"Run: mirror set grant {agent_name} {app_id} granted",
        )

    def edit(data: Any) -> None:
        for entry in data["apps"]:
            if entry["id"] == app_id:
                entry["remote"] = {"hostname": hostname, "auth": "oauth"}

    edit_manifest(project, edit)
    say(f"{app_id} is exposed at {hostname} in mirror.yaml")
    if any(c.applies in ("restart", "rebuild") for c in env_svc.pending_changes(project)):
        env_svc.apply_changes(project, on_step=say)
    person, identities = agents_svc.issue(project, agent)
    identity = identities.get(app_id)
    if identity is None or not identity.password:
        raise MirrorError(
            f"No sign-in was issued for {agent_name} on {app_id}.",
            "The sandbox may not be up with the ingress.",
            "Run: mirror up, then expose again.",
        )
    caddy, nginx = proxy_settings(hostname, port)
    endpoint = identity.env.get(
        f"{app_id.upper().replace('-', '_')}_MCP_URL", f"https://{hostname}"
    )
    return Exposure(
        app_id=app_id,
        agent=agent_name,
        public_url=endpoint,
        local=f"127.0.0.1:{port}",
        username=person.username,
        password=identity.password,
        caddy=caddy,
        nginx=nginx,
    )


def unexpose(project: Project, app_id: str) -> Change:
    """Stop exposing an MCP server: the ingress goes when the sandbox next restarts."""
    from mirrordimensions.service.systems import edit_manifest

    manifest = agents_svc._manifest(project)  # pyright: ignore[reportPrivateUsage]
    app = next((a for a in manifest.apps if a.id == app_id), None)
    if app is None or app.remote is None:
        raise MirrorError(f"{app_id} is not exposed.", "", "Run: mirror changes")
    before = app.remote.hostname

    def edit(data: Any) -> None:
        for entry in data["apps"]:
            if entry["id"] == app_id:
                entry.pop("remote", None)

    edit_manifest(project, edit)
    return Change(
        kind="system",
        target=app_id,
        what=f"{app_id}: no longer exposed",
        before=before,
        applies="restart",
    )


def relay(
    project: Project, port: int = DEFAULT_PORT, ready: Callable[[], None] | None = None
) -> None:
    """Carry connections from 127.0.0.1:port into this world's ingress until interrupted."""
    from mirrordimensions.network import ingress_relay, sandbox
    from mirrordimensions.service.sandbox import _docker, world_plan  # pyright: ignore[reportPrivateUsage]

    plan = world_plan(project)
    docker, *_ = _docker()
    if not plan.exposed or not docker.is_running(sandbox.INGRESS_NAME):
        raise MirrorError(
            "The ingress is not running.",
            "Nothing in this world is exposed, or the sandbox has not restarted since.",
            "Run: mirror world expose <mcp-server> --hostname <name> --agent <remote agent>",
        )
    if docker.labels(sandbox.INGRESS_NAME).get(sandbox.LABEL) != plan.world:
        raise MirrorError("The ingress running is another world's.", "", "Run: mirror up here")
    import json

    from mirrordimensions.hostos.files import write_text

    marker = project.state_dir / "expose.json"  # for `mirror doctor` to probe from the sandbox

    def listening() -> None:
        write_text(marker, json.dumps({"port": port}) + "\n", owner_only=True)
        if ready is not None:
            ready()

    try:
        ingress_relay.serve(docker, port, listening)
    except OSError as exc:
        raise MirrorError(
            f"The relay could not listen on 127.0.0.1:{port}.",
            str(exc),
            "Another program may use that port. Try: --port <another>",
        ) from exc
    finally:
        marker.unlink(missing_ok=True)
