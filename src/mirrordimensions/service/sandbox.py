# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""Bring a project's sealed network up and down, and prove it with doctor (M1).

Until twins exist (M2), each app is served by a stub web server behind the gateway.
"""

from __future__ import annotations

from collections.abc import Callable

from mirrordimensions.config.loader import load_model
from mirrordimensions.config.manifest import Manifest
from mirrordimensions.engine.docker_api import Docker
from mirrordimensions.engine.registry import get_engine
from mirrordimensions.errors import MirrorError
from mirrordimensions.hostos.awake import keep_awake
from mirrordimensions.hostos.lock import ProjectLock
from mirrordimensions.network import sandbox
from mirrordimensions.network.certs import ensure_leaves
from mirrordimensions.network.egress_check import DoctorReport, run_doctor
from mirrordimensions.network.events import Collector
from mirrordimensions.project import Project

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
        names = sandbox.up(docker, plan, leaves, secrets=[])
    return names


def down(project: Project) -> None:
    plan = sandbox.plan_from(_manifest(project))
    docker, *_ = _docker()
    with ProjectLock(project.state_dir, "down"):
        sandbox.down(docker, plan)


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
    with keep_awake("Checking the sandbox"):
        return run_doctor(plan, docker, collector, ca_pem, driver, boundary)
