# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""Build the world, snapshot it, and reset to a snapshot (M3)."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from datetime import UTC, datetime
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


class _Run:
    """One build, as six idempotent stages. Each can run again after a failure without harm:
    generation is deterministic, the network comes up idempotently, and seeding records each
    finished system in build.json and skips it next time."""

    def __init__(self, project: Project, force: bool, on_step: StepFn) -> None:
        self.project = project
        self.force = force
        self.on_step = on_step
        self.manifest: Manifest = _manifest(project)
        self.plan = sandbox.plan_from(self.manifest)
        self.docker, *_ = _docker()
        self.secrets = app_secrets(project, self.manifest)
        self.world = generate(self.manifest)
        self.text = world_json(self.world)
        self.digest = hashlib.sha256(self.text.encode()).hexdigest()[:16]
        self.state_path = project.state_dir / "build.json"
        self.state: dict[str, Any] = (
            json.loads(self.state_path.read_text(encoding="utf-8"))
            if self.state_path.is_file()
            else {}
        )
        self.fresh = force or self.state.get("world") != self.digest
        self.seeded: dict[str, dict[str, int]] = (
            {} if self.fresh else dict(self.state.get("seeded", {}))
        )
        self.result: BuildResult | None = None

    def stages(self) -> list[Callable[[], None]]:
        return [self.generate, self.network, self.start, self.load, self.traces, self.snapshot]

    def generate(self) -> None:
        write_text(self.project.state_dir / "world.json", self.text, owner_only=True)
        w = self.world
        _step(
            self.on_step,
            f"World generated from seed {self.manifest.company.seed}: {len(w.people)} people, "
            f"{len(w.repositories)} repositories, {sum(len(r.issues) for r in w.repositories)} issues, "
            f"{sum(len(c.messages) for c in w.channels)} messages",
        )

    def network(self) -> None:
        if self.fresh:
            sandbox.down(self.docker, self.plan, purge=True)
            self.state = {}
            self.fresh = False  # a later stage re-run in this build must not purge again
        leaves = ensure_leaves(
            self.project.state_dir / "ca",
            self.project.state_dir / "certs",
            self.plan.tls_names,
            self.plan.seed,
        )
        sandbox.up(self.docker, self.plan, leaves, secrets=[], app_secrets=self.secrets)
        _step(self.on_step, "Network ready: DNS, gateway, certificates")

    def start(self) -> None:
        relay = Relay(self.docker)
        for app in _twins(self.plan):
            twin = get_twin(app.product)
            assert twin is not None  # noqa: S101
            twin.bootstrap(self.docker, relay, sandbox.twin_context(self.plan, app, self.secrets))
        _step(
            self.on_step,
            "Systems started: " + ", ".join(str(a.product) for a in _twins(self.plan)),
        )

    def load(self) -> None:
        now = datetime.now(UTC)  # seeding time; the world itself is defined by offsets from it
        relay = Relay(self.docker)
        for app in _twins(self.plan):
            if app.id in self.seeded:
                continue
            twin = get_twin(app.product)
            assert twin is not None  # noqa: S101
            ctx = sandbox.twin_context(self.plan, app, self.secrets)
            self.seeded[app.id] = twin.seed(self.docker, relay, ctx, self.world, now)
            write_text(
                self.state_path,
                json.dumps({"world": self.digest, "seeded": self.seeded}, indent=2) + "\n",
                owner_only=True,
            )
            _step(
                self.on_step,
                f"{app.product} seeded: "
                + ", ".join(f"{v} {k}" for k, v in self.seeded[app.id].items()),
            )

    def traces(self) -> None:
        relay = Relay(self.docker)
        found: list[str] = []
        for app in _twins(self.plan):
            twin = get_twin(app.product)
            assert twin is not None  # noqa: S101
            found += twin.setup_traces(
                self.docker, relay, sandbox.twin_context(self.plan, app, self.secrets)
            )
        if found:
            raise MirrorError(
                "Building the world left traces a real company would not have.",
                "; ".join(found[:4]),
                "Report this as a bug, then run: mirror world create --resume",
            )
        _step(
            self.on_step, "No setup traces: tokens, import files, jobs and audit entries are gone"
        )

    def snapshot(self) -> None:
        sdir = self.project.state_dir / "snapshots"
        before = _dumps(self.docker, self.plan, self.secrets)
        containers, vols = _containers_and_volumes(self.plan, self.secrets)
        info = snap.save(self.docker, "base", vols, containers, sdir / "index.json")
        write_text(
            sdir / "base.dump.json", json.dumps(before, sort_keys=True) + "\n", owner_only=True
        )
        _step(self.on_step, f'Snapshot saved as "base" ({info.seconds}s)')
        started = time.time()
        snap.restore(self.docker, "base", sdir / "index.json", containers)
        _start_twins(self.docker, self.plan, self.secrets)
        restore_seconds = round(time.time() - started, 1)
        after = _dumps(self.docker, self.plan, self.secrets)
        if after != before:
            raise MirrorError(
                "The base snapshot does not restore exactly.",
                "Differences: " + ", ".join(diff_dumps(before, after)[:5]),
                "Report this as a bug; the world cannot be reset reliably.",
            )
        _step(self.on_step, f"Snapshot verified by a restore-and-compare ({restore_seconds}s)")
        self.result = BuildResult(
            world_hash=self.digest,
            seeded=self.seeded,
            snapshot_seconds=info.seconds,
            restore_seconds=restore_seconds,
            verified=True,
        )


def build(project: Project, force: bool = False, on_step: StepFn = None) -> BuildResult:
    with ProjectLock(project.state_dir, "build"), keep_awake("Building the world"):
        run = _Run(project, force, on_step)
        for stage in run.stages():
            stage()
    assert run.result is not None  # noqa: S101
    return run.result


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


def run_stages(
    stages: list[Callable[[], None]],
    start: int,
    record: Callable[[int, str | None], None],
    on_stage: StepFn = None,
) -> int:
    """Run stages[start-1:], recording each as it finishes; on failure record where it stopped
    and re-raise. Returns the last finished stage. Stage numbers are 1-based."""
    from mirrordimensions.service.worlddef import STAGES

    last = start - 1
    for number in range(start, len(stages) + 1):
        try:
            stages[number - 1]()
        except MirrorError as exc:
            record(last, f"stage {number} ({STAGES[number - 1]}): {exc.what}")
            raise
        last = number
        record(last, None)
        _step(on_stage, f"{number}. {STAGES[number - 1]}")
    return last


def create_world(
    project: Project, resume: bool = False, from_stage: int | None = None, on_stage: StepFn = None
) -> int:
    """Run the eight creation stages, recording each; resume from the first unfinished one,
    or from the first stage a change to the definition affects."""
    from mirrordimensions.service import sandbox as sandbox_svc
    from mirrordimensions.service import worlddef

    manifest = _manifest(project)
    record_path = project.state_dir / "create.json"
    record: dict[str, Any] = (
        json.loads(record_path.read_text(encoding="utf-8")) if record_path.is_file() else {}
    )
    start = worlddef.resume_stage(record, worlddef.definition_hash(manifest), resume, from_stage)
    if start > len(worlddef.STAGES):
        _step(on_stage, "Already created; nothing in the definition changed")
        return len(worlddef.STAGES)
    unavailable = [a.id for a in manifest.apps if a.build == "unavailable"]
    if unavailable:
        _step(on_stage, "Left out (no twin yet): " + ", ".join(unavailable))

    def checks() -> None:
        report = sandbox_svc.doctor(project)
        if report.isolation == "failed":
            failed = ", ".join(c.name for c in report.failed[:3])
            raise MirrorError(
                "The world's checks failed.", f"Failed: {failed}.", "Run: mirror doctor"
            )

    with ProjectLock(project.state_dir, "build"), keep_awake("Creating the world"):
        run = _Run(project, force=start == 1 and bool(record), on_step=None)
        stages = [*run.stages(), checks, lambda: None]
        return run_stages(
            stages,
            start,
            lambda stage, failed: worlddef.record_stage(project, stage, manifest, failed),
            on_stage,
        )
