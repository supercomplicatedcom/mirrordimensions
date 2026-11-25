# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""The project's health at a glance: state, engine, the sandbox's containers, snapshots and
the last isolation check (build spec, "Portal", Health screen).

`mirror doctor` takes half a minute, so its last report is kept (`.mirror/doctor.json`) and
shown with its age; running the checks again is one action away.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from mirrordimensions.engine.docker_api import Docker
from mirrordimensions.engine.registry import get_engine
from mirrordimensions.errors import MirrorError
from mirrordimensions.network import sandbox
from mirrordimensions.project import Project
from mirrordimensions.service import project as project_svc
from mirrordimensions.service import sandbox as sandbox_svc
from mirrordimensions.twins.relay import RELAY_NAME as CONTROL_RELAY

DOCTOR_FILE = sandbox_svc.DOCTOR_FILE


class Container(BaseModel):
    name: str
    role: str
    running: bool


class Snapshot(BaseModel):
    name: str
    created: str
    volumes: int


class Health(BaseModel):
    project: str | None
    state: str
    engine: str = Field(description="absent, stopped, running or broken")
    engine_detail: str = ""
    up: bool
    containers: list[Container] = Field(default_factory=list[Container])
    snapshots: list[Snapshot] = Field(default_factory=list[Snapshot])
    doctor: dict[str, Any] | None = Field(
        default=None, description="The last `mirror doctor` report, with `checked_at`"
    )


ROLES = {
    sandbox.DNS_NAME: "resolver",
    sandbox.APPS_DNS_NAME: "systems' resolver",
    sandbox.GATEWAY_NAME: "gateway",
    sandbox.RELAY_NAME: "kernel log relay",
    sandbox.TRACER_NAME: "tracer",
    CONTROL_RELAY: "control relay",
}


def list_snapshots(project: Project) -> list[Snapshot]:
    path = project.state_dir / "snapshots" / "index.json"
    if not path.is_file():
        return []
    data: dict[str, dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))
    return [
        Snapshot(
            name=name, created=str(info.get("created", "")), volumes=len(info.get("volumes", []))
        )
        for name, info in sorted(data.items())
    ]


def _doctor_path(project: Project) -> Path:
    return project.state_dir / DOCTOR_FILE


def last_doctor(project: Project) -> dict[str, Any] | None:
    path = _doctor_path(project)
    if not path.is_file():
        return None
    try:
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return None
    return data


def run_doctor(project: Project, latency_budget_ms: float = 10.0) -> dict[str, Any]:
    """`mirror doctor`; its report is kept by the doctor itself."""
    sandbox_svc.doctor(project, latency_budget_ms)
    return last_doctor(project) or {}


def health(project: Project, containers: bool = True) -> Health:
    """`containers=False` skips the engine: just the project's own files, for quick reads."""
    st = project_svc.status(project.root)
    if not containers:
        return Health(
            project=st.name,
            state=st.state,
            engine="unknown",
            up=False,
            snapshots=list_snapshots(project),
            doctor=last_doctor(project),
        )
    engine = get_engine()
    try:
        es = engine.status()
        engine_state, detail = es.state, f"{es.driver} · {es.arch or '?'} · {es.boundary or '?'}"
    except MirrorError as exc:
        engine_state, detail = "broken", exc.what
    found: list[Container] = []
    if engine_state == "running":
        docker = Docker(engine.docker_endpoint())
        plan = sandbox_svc.world_plan(project)
        names = [
            *ROLES,
            *(a.container for a in plan.apps),
            *(a.db_container for a in plan.apps if a.db_container),
        ]
        for name in names:
            role = ROLES.get(name) or next(
                (
                    f"{a.id} ({'database' if name == a.db_container else a.product or a.kind})"
                    for a in plan.apps
                    if name in (a.container, a.db_container)
                ),
                "system",
            )
            found.append(Container(name=name, role=role, running=docker.is_running(name)))
    return Health(
        project=st.name,
        state=st.state,
        engine=engine_state,
        engine_detail=detail,
        up=any(c.running and c.name == sandbox.GATEWAY_NAME for c in found),
        containers=found,
        snapshots=list_snapshots(project),
        doctor=last_doctor(project),
    )
