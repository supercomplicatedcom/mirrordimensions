# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""Bring a project's sealed network up and down, and prove it with doctor (M1).

Until twins exist (M2), each app is served by a stub web server behind the gateway.
"""

from __future__ import annotations

import json
import secrets as secrets_module
from collections.abc import Callable

from mirrordimensions.config.loader import load_model
from mirrordimensions.config.manifest import Manifest
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


def up(project: Project, on_step: StepFn = None) -> list[str]:
    manifest = _manifest(project)
    plan = sandbox.plan_from(manifest)
    docker, *_ = _docker()
    with ProjectLock(project.state_dir, "up"), keep_awake("Starting the sandbox"):
        leaves = ensure_leaves(
            project.state_dir / "ca", project.state_dir / "certs", plan.tls_names, plan.seed
        )
        if on_step:
            on_step(f"{len(leaves)} certificates for {', '.join(plan.tls_names)}")
        names = sandbox.up(
            docker,
            plan,
            leaves,
            secrets=[],
            app_secrets=app_secrets(project, manifest),
            on_step=on_step,
        )
    return names


def down(project: Project, purge: bool = False) -> None:
    plan = sandbox.plan_from(_manifest(project))
    docker, *_ = _docker()
    with ProjectLock(project.state_dir, "down"):
        sandbox.down(docker, plan, purge=purge)


def doctor(project: Project) -> DoctorReport:
    plan = sandbox.plan_from(_manifest(project))
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
        return run_doctor(plan, docker, collector, ca_pem, driver, boundary, twin_fetch)


def admin_fetcher(project: Project, app_id: str) -> Callable[[str, str, bytes], tuple[int, bytes]]:
    """For `mirror system try`: ask a product directly, through the relay, as its administrator."""
    manifest = _manifest(project)
    plan = sandbox.plan_from(manifest)
    docker, *_ = _docker()
    app = next(a for a in plan.apps if a.id == app_id)
    twin = get_twin(app.product)
    if twin is None:
        raise MirrorError(
            f"{app_id} has no twin.",
            "Only systems with a twin can be tried.",
            "Run: mirror system list",
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
