# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""Build the world, snapshot it, and reset to a snapshot (M3)."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from typing import Any, cast

from pydantic import BaseModel

from mirrordimensions.config.manifest import Manifest
from mirrordimensions.engine.docker_api import Docker
from mirrordimensions.errors import MirrorError
from mirrordimensions.hostos.awake import keep_awake
from mirrordimensions.hostos.files import write_text
from mirrordimensions.hostos.lock import ProjectLock
from mirrordimensions.network import sandbox
from mirrordimensions.network.certs import ensure_leaves
from mirrordimensions.project import Project
from mirrordimensions.service.sandbox import _docker, _manifest, app_secrets  # pyright: ignore[reportPrivateUsage]
from mirrordimensions.snapshot import volumes as snap
from mirrordimensions.twins.base import get_twin
from mirrordimensions.twins.relay import Relay
from mirrordimensions.world.generate import generate, world_json

StepFn = Callable[[str], None] | None


class BuildResult(BaseModel):
    world_hash: str
    seeded: dict[str, dict[str, int]]
    snapshot_seconds: float
    restore_seconds: float
    verified: bool


class ResetResult(BaseModel):
    snapshot: str
    seconds: float
    identical: bool
    differences: list[str]


def _step(on_step: StepFn, text: str) -> None:
    if on_step:
        on_step(text)


def _twins(plan: sandbox.Plan) -> list[sandbox.App]:
    return [a for a in plan.apps if a.visibility != "absent" and get_twin(a.product) is not None]


def _dumps(docker: Docker, plan: sandbox.Plan, secrets: dict[str, str]) -> dict[str, Any]:
    relay = Relay(docker)
    out: dict[str, Any] = {}
    for app in _twins(plan):
        twin = get_twin(app.product)
        assert twin is not None  # noqa: S101
        ctx = sandbox.twin_context(plan, app, secrets)
        twin.bootstrap(docker, relay, ctx)
        out[app.id] = twin.dump_state(relay, ctx)
    return out


def _start_twins(docker: Docker, plan: sandbox.Plan, secrets: dict[str, str]) -> None:
    relay = Relay(docker)
    for app in _twins(plan):
        twin = get_twin(app.product)
        assert twin is not None  # noqa: S101
        ctx = sandbox.twin_context(plan, app, secrets)
        docker.start(ctx.db_container)
        docker.start(ctx.app_container)
    for app in _twins(plan):
        twin = get_twin(app.product)
        assert twin is not None  # noqa: S101
        twin.wait_ready(relay, sandbox.twin_context(plan, app, secrets), timeout_s=300)


def _containers_and_volumes(
    plan: sandbox.Plan, secrets: dict[str, str]
) -> tuple[list[str], list[str]]:
    containers: list[str] = []
    vols: list[str] = []
    for app in _twins(plan):
        twin = get_twin(app.product)
        assert twin is not None  # noqa: S101
        ctx = sandbox.twin_context(plan, app, secrets)
        containers += [ctx.app_container, ctx.db_container]
        vols += twin.volumes(ctx)
    return containers, vols


def diff_dumps(before: Any, after: Any, prefix: str = "") -> list[str]:
    """Paths where two state dumps differ, for messages and the side-effect comparison."""
    if before == after:
        return []
    if isinstance(before, dict) and isinstance(after, dict):
        b = cast(dict[str, Any], before)
        a = cast(dict[str, Any], after)
        out: list[str] = []
        for key in sorted(set(b) | set(a)):
            out += diff_dumps(b.get(key), a.get(key), f"{prefix}/{key}")
        return out
    if isinstance(before, list) and isinstance(after, list):
        bl = cast(list[Any], before)
        al = cast(list[Any], after)
        if len(bl) == len(al):
            out = []
            for i, (x, y) in enumerate(zip(bl, al, strict=True)):
                out += diff_dumps(x, y, f"{prefix}[{i}]")
            return out
    return [prefix or "/"]


def build(project: Project, force: bool = False, on_step: StepFn = None) -> BuildResult:
    manifest: Manifest = _manifest(project)
    plan = sandbox.plan_from(manifest)
    docker, *_ = _docker()
    secrets = app_secrets(project, manifest)
    with ProjectLock(project.state_dir, "build"), keep_awake("Building the world"):
        world = generate(manifest)
        text = world_json(world)
        digest = hashlib.sha256(text.encode()).hexdigest()[:16]
        write_text(project.state_dir / "world.json", text, owner_only=True)
        _step(
            on_step,
            f"World generated from seed {manifest.company.seed}: {len(world.people)} people, "
            f"{len(world.repositories)} repositories, {sum(len(r.issues) for r in world.repositories)} issues, "
            f"{sum(len(c.messages) for c in world.channels)} messages",
        )
        state_path = project.state_dir / "build.json"
        state: dict[str, Any] = (
            json.loads(state_path.read_text(encoding="utf-8")) if state_path.is_file() else {}
        )
        fresh = force or state.get("world") != digest
        if fresh:
            sandbox.down(docker, plan, purge=True)
        leaves = ensure_leaves(
            project.state_dir / "ca", project.state_dir / "certs", plan.tls_names, plan.seed
        )
        sandbox.up(docker, plan, leaves, secrets=[], app_secrets=secrets)
        _step(on_step, "Network ready: DNS, gateway, certificates")
        from mirrordimensions.twins.gitea.seed import GiteaSeeder, utc_now
        from mirrordimensions.twins.mattermost import seed as mattermost_seed

        now = utc_now()
        relay = Relay(docker)
        seeded: dict[str, dict[str, int]] = dict(state.get("seeded", {})) if not fresh else {}
        for app in _twins(plan):
            if app.id in seeded:
                continue
            twin = get_twin(app.product)
            assert twin is not None  # noqa: S101
            ctx = sandbox.twin_context(plan, app, secrets)
            twin.bootstrap(docker, relay, ctx)
            if app.product == "gitea":
                seeded[app.id] = GiteaSeeder(twin, relay, ctx, docker).seed(world, now)
            elif app.product == "mattermost":
                seeded[app.id] = mattermost_seed.seed(docker, ctx, world, now)
            write_text(
                state_path,
                json.dumps({"world": digest, "seeded": seeded}, indent=2) + "\n",
                owner_only=True,
            )
            _step(
                on_step,
                f"{app.product} seeded: "
                + ", ".join(f"{v} {k}" for k, v in seeded[app.id].items()),
            )
        before = _dumps(docker, plan, secrets)
        containers, vols = _containers_and_volumes(plan, secrets)
        info = snap.save(
            docker, "base", vols, containers, project.state_dir / "snapshots" / "index.json"
        )
        write_text(
            project.state_dir / "snapshots" / "base.dump.json",
            json.dumps(before, sort_keys=True) + "\n",
            owner_only=True,
        )
        _step(on_step, f'Snapshot saved as "base" ({info.seconds}s)')
        started = time.time()
        snap.restore(docker, "base", project.state_dir / "snapshots" / "index.json", containers)
        _start_twins(docker, plan, secrets)
        restore_seconds = round(time.time() - started, 1)
        after = _dumps(docker, plan, secrets)
        verified = after == before
        if not verified:
            raise MirrorError(
                "The base snapshot does not restore exactly.",
                "Differences: " + ", ".join(diff_dumps(before, after)[:5]),
                "Report this as a bug; the world cannot be reset reliably.",
            )
        _step(on_step, f"Snapshot verified by a restore-and-compare ({restore_seconds}s)")
        return BuildResult(
            world_hash=digest,
            seeded=seeded,
            snapshot_seconds=info.seconds,
            restore_seconds=restore_seconds,
            verified=verified,
        )


def reset(project: Project, name: str = "base", on_step: StepFn = None) -> ResetResult:
    manifest = _manifest(project)
    plan = sandbox.plan_from(manifest)
    docker, *_ = _docker()
    secrets = app_secrets(project, manifest)
    dump_path = project.state_dir / "snapshots" / f"{name}.dump.json"
    with ProjectLock(project.state_dir, "reset"), keep_awake("Resetting the world"):
        containers, _ = _containers_and_volumes(plan, secrets)
        started = time.time()
        snap.restore(docker, name, project.state_dir / "snapshots" / "index.json", containers)
        _start_twins(docker, plan, secrets)
        seconds = round(time.time() - started, 1)
        _step(on_step, f'Restored "{name}" in {seconds}s')
        expected = (
            json.loads(dump_path.read_text(encoding="utf-8")) if dump_path.is_file() else None
        )
        actual = _dumps(docker, plan, secrets)
        differences = (
            diff_dumps(expected, actual)
            if expected is not None
            else ["no saved dump to compare with"]
        )
    return ResetResult(
        snapshot=name, seconds=seconds, identical=not differences, differences=differences[:20]
    )


def save_snapshot(project: Project, name: str) -> snap.SnapshotInfo:
    manifest = _manifest(project)
    plan = sandbox.plan_from(manifest)
    docker, *_ = _docker()
    secrets = app_secrets(project, manifest)
    with ProjectLock(project.state_dir, "snapshot"):
        before = _dumps(docker, plan, secrets)
        containers, vols = _containers_and_volumes(plan, secrets)
        info = snap.save(
            docker, name, vols, containers, project.state_dir / "snapshots" / "index.json"
        )
        write_text(
            project.state_dir / "snapshots" / f"{name}.dump.json",
            json.dumps(before, sort_keys=True) + "\n",
            owner_only=True,
        )
        _start_twins(docker, plan, secrets)
    return info


def create_world(
    project: Project, resume: bool = False, from_stage: int | None = None, on_stage: StepFn = None
) -> list[str]:
    """Run the eight creation stages, recording each; resume from the first unfinished one."""
    from mirrordimensions.service import sandbox as sandbox_svc
    from mirrordimensions.service import worlddef

    manifest = _manifest(project)
    status = worlddef.world_status(project)
    record_path = project.state_dir / "create.json"
    record: dict[str, Any] = (
        json.loads(record_path.read_text(encoding="utf-8")) if record_path.is_file() else {}
    )
    start = 1
    if from_stage is not None:
        start = from_stage
    elif resume and record:
        start = min(
            int(record.get("last_stage", 0)) + 1,
            worlddef.first_stage_affected(
                record.get("hashes", {}), worlddef.definition_hash(manifest)
            ),
        )
    done: list[str] = []
    if status.unavailable:
        _step(on_stage, "Left out (no twin yet): " + ", ".join(status.unavailable))

    def finish(stage: int) -> None:
        worlddef.record_stage(project, stage, manifest)
        done.append(worlddef.STAGES[stage - 1])
        _step(on_stage, f"{stage}. {worlddef.STAGES[stage - 1]}")

    try:
        if start <= 6:
            force = start <= 4 and bool(record) and not resume
            build(project, force=force or (start <= 1 and bool(record)), on_step=None)
            for stage in range(max(start, 1), 7):
                finish(stage)
        if start <= 7:
            report = sandbox_svc.doctor(project)
            if report.isolation == "failed":
                failed = ", ".join(c.name for c in report.failed[:3])
                worlddef.record_stage(project, 6, manifest, failed=f"checks failed: {failed}")
                raise MirrorError(
                    "The world's checks failed.",
                    f"Failed: {failed}.",
                    "Run: mirror doctor, then mirror world create --resume",
                )
            finish(7)
        if start <= 8:
            finish(8)
    except MirrorError:
        raise
    return done
