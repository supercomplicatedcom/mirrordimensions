# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""Bring a project's sealed network up and down, and prove it with doctor (M1).

Until twins exist (M2), each app is served by a stub web server behind the gateway.
"""

from __future__ import annotations

import ipaddress
import json
import os
import secrets as secrets_module
import socket
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path

from mirrordimensions.config.loader import load_model
from mirrordimensions.config.manifest import Manifest
from mirrordimensions.engine.base import update_note
from mirrordimensions.engine.docker_api import Docker
from mirrordimensions.engine.registry import get_engine
from mirrordimensions.errors import MirrorError
from mirrordimensions.hostos.awake import keep_awake
from mirrordimensions.hostos.files import write_text
from mirrordimensions.hostos.lock import ProjectLock
from mirrordimensions.network import sandbox
from mirrordimensions.network.certs import ensure_leaves
from mirrordimensions.network.egress_check import DoctorReport, run_doctor
from mirrordimensions.network.events import Collector
from mirrordimensions.project import Project
from mirrordimensions.twins.base import get_twin
from mirrordimensions.twins.relay import Relay

StepFn = Callable[[str], None] | None


def _manifest(project: Project) -> Manifest:
    manifest, problems = load_model(project.manifest_path, Manifest)
    if manifest is None:
        first = problems[0].render() if problems else "unknown problem"
        raise MirrorError("mirror.yaml is not valid.", first, "Run: mirror validate")
    return manifest


def world_plan(project: Project, manifest: Manifest | None = None) -> sandbox.Plan:
    """The world's plan, with MCP servers' tools loaded and the install root known."""
    result = sandbox.plan_from(manifest or _manifest(project), project.root)
    ca = project.state_dir / "ca" / "root-ca.crt"
    if ca.is_file():
        result.ca_pem = ca.read_bytes()
    return result


def _docker() -> tuple[Docker, str, str, float]:
    engine = get_engine()
    status = engine.status()
    if status.state != "running":
        raise MirrorError(
            "The engine is not running.",
            f"Its state is {status.state}.",
            "Run: mirror engine start",
        )
    return (
        Docker(engine.docker_endpoint()),
        engine.name,
        status.boundary or "",
        status.clock_offset_s or 0.0,
    )


SECRET_KEYS = ("db_password", "admin_password", "user_password", "secret_key", "internal_token")


def app_secrets(project: Project, manifest: Manifest) -> dict[str, str]:
    """Per-install secrets for each twin, generated once and kept owner-only on the host."""
    path = project.state_dir / "secrets.json"
    current: dict[str, str] = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    changed = False
    for app in manifest.apps:
        for key in SECRET_KEYS:
            name = f"{app.id}:{key}"
            if name not in current:
                current[name] = secrets_module.token_urlsafe(24)
                changed = True
    if changed:
        write_text(path, json.dumps(current, indent=2, sort_keys=True) + "\n", owner_only=True)
    return current


Resolver = Callable[[str, int], str]


def _resolve_ipv4(host: str, port: int) -> str:
    """The provider's address, looked up on the host (never from inside the sandbox)."""
    try:
        infos = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)
    except OSError as exc:
        raise MirrorError(
            f"Cannot look up the model host {host}.",
            str(exc),
            "Check the host name in mirror.yaml and this machine's network.",
        ) from exc
    return str(infos[0][4][0])


def open_model_routes(
    plan: sandbox.Plan, environ: Mapping[str, str], resolve: Resolver = _resolve_ipv4
) -> list[tuple[str, str, int]]:
    """Fill each model route's one upstream and real credential, and return the firewall
    entries that let exactly those out. The credential is read from the host's environment;
    it is given to the gateway only, never to anything the agent can reach."""
    for model in plan.models:
        if model.upstream:
            address, _, port = model.upstream.rpartition(":")
            model.port = int(port)
            model.ip = address if _is_ipv4(address) else resolve(address, model.port)
        else:
            model.port = 443
            model.ip = resolve(model.host, model.port)
        if model.credential_env:
            value = environ.get(model.credential_env)
            if not value:
                raise MirrorError(
                    f"Model route {model.name!r} needs {model.credential_env}, which is unset.",
                    "The gateway adds the real credential; the agent holds only a placeholder.",
                    f"Set {model.credential_env} in this shell, then try again.",
                )
            model.credential = value
    return sandbox.egress_entries(plan)


def _is_ipv4(text: str) -> bool:
    try:
        return isinstance(ipaddress.ip_address(text), ipaddress.IPv4Address)
    except ValueError:
        return False


def apply_model_routes(plan: sandbox.Plan) -> None:
    """Resolve the model routes and set the engine firewall to exactly their upstreams."""
    entries = open_model_routes(plan, os.environ) if plan.models else []
    get_engine().set_egress_allow(entries)


def up(project: Project, on_step: StepFn = None) -> list[str]:
    manifest = _manifest(project)
    plan = world_plan(project, manifest)
    docker, *_ = _docker()
    with ProjectLock(project.state_dir, "up"), keep_awake("Starting the sandbox"):
        leaves = ensure_leaves(
            project.state_dir / "ca", project.state_dir / "certs", plan.tls_names, plan.seed
        )
        if on_step:
            on_step(f"{len(leaves)} certificates for {', '.join(plan.tls_names)}")
        apply_model_routes(plan)
        names = sandbox.up(
            docker,
            plan,
            leaves,
            secrets=[],
            app_secrets=app_secrets(project, manifest),
            on_step=on_step,
        )
        from mirrordimensions.service.changes import record_applied

        record_applied(project, manifest)  # the gateway has these rules and visibility now
    return names


def down(project: Project, purge: bool = False) -> None:
    plan = world_plan(project)
    docker, *_ = _docker()
    with ProjectLock(project.state_dir, "down"):
        sandbox.down(docker, plan, purge=purge)
        get_engine().set_egress_allow([])  # with the world down, nothing may leave


PORTAL_FILE = "portal.json"  # written by `mirror portal` while it serves this project


def _serving_port(path: Path) -> int | None:
    """The port a marker names, if something listens there on 127.0.0.1. A server that was
    killed (or stopped by a signal its web server re-raises) leaves its marker behind."""
    import socket

    try:
        port = int(json.loads(path.read_text(encoding="utf-8"))["port"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if not 0 < port < 65536:
        return None
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return port
    except OSError:
        return None


def running_portal_port(project: Project) -> int | None:
    """The port of this project's portal, if one is serving it."""
    return _serving_port(project.state_dir / PORTAL_FILE)


def running_operator_port(project: Project) -> int | None:
    """The port of this project's operator MCP server over HTTP, if one is serving."""
    return _serving_port(project.state_dir / "operator.json")  # `mirror mcp serve --http`


DOCTOR_FILE = "doctor.json"  # the last report, for the portal's Health screen


def doctor(project: Project, latency_budget_ms: float = 10.0) -> DoctorReport:
    plan = world_plan(project)
    docker, driver, boundary, offset = _docker()
    for name in (sandbox.DNS_NAME, sandbox.GATEWAY_NAME, sandbox.RELAY_NAME):
        if not docker.is_running(name):
            raise MirrorError("The sandbox is not up.", f"{name} is not running.", "Run: mirror up")
    bridges = {
        f"br-{docker.network_id(n)[:12]}": n for n in (sandbox.LAN, sandbox.APPS, sandbox.UPLINK)
    }
    collector = Collector(docker, project.state_dir / "sandbox" / "events.jsonl", bridges, offset)
    collector.start()
    ca_pem = (project.state_dir / "ca" / "root-ca.crt").read_bytes()
    twin_fetch = _twin_fetcher(project, plan, docker)
    with keep_awake("Checking the sandbox"):
        report = run_doctor(
            plan,
            docker,
            collector,
            ca_pem,
            driver,
            boundary,
            twin_fetch,
            latency_budget_ms,
            portal_port=running_portal_port(project),
            operator_port=running_operator_port(project),
        )
    note = update_note(get_engine().status().versions, datetime.now(UTC).date())
    if note:
        report.notes.append(note)
    # Kept for the portal's Health screen, which shows the last check and its age.
    kept = report.model_dump(mode="json")
    kept["checked_at"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    write_text(project.state_dir / DOCTOR_FILE, json.dumps(kept, indent=2) + "\n", owner_only=True)
    return report


def admin_fetcher(project: Project, app_id: str) -> Callable[[str, str, bytes], tuple[int, bytes]]:
    """For `mirror system try`: ask a product directly, through the relay, as its administrator."""
    manifest = _manifest(project)
    plan = world_plan(project, manifest)
    docker, *_ = _docker()
    app = next(a for a in plan.apps if a.id == app_id)
    twin = get_twin(app.product)
    if twin is None:
        raise MirrorError(
            f"{app_id} has no twin.",
            "Only systems with a twin can be tried.",
            "Run: mirror system list",
        )
    if docker.labels(sandbox.GATEWAY_NAME).get(sandbox.LABEL) != plan.world:
        # Every world's sandbox uses the same container names: never ask another world's.
        raise MirrorError(
            "The sandbox is not up.",
            f"No sandbox of {plan.world} is running in the engine.",
            "Run: mirror up",
        )
    relay = Relay(docker)
    ctx = sandbox.twin_context(plan, app, app_secrets(project, manifest))
    twin.bootstrap(docker, relay, ctx)
    return lambda method, path, body: twin.admin_fetch(relay, ctx, method, path, body)  # type: ignore[attr-defined]


def _twin_fetcher(
    project: Project, plan: sandbox.Plan, docker: Docker
) -> Callable[[str], None] | None:
    """A function that asks the first twin with a URL-fetching feature to fetch a URL."""
    secrets = app_secrets(project, _manifest(project))
    relay = Relay(docker)
    for app in plan.apps:
        twin = get_twin(app.product)
        fetch = getattr(twin, "fetch_external", None)
        if twin is None or fetch is None or app.visibility == "absent":
            continue
        ctx = sandbox.twin_context(plan, app, secrets)
        twin.bootstrap(docker, relay, ctx)
        return lambda url: fetch(relay, ctx, url)
    return None
