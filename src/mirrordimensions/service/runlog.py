# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""Reading runs: the list, one result, its events a page at a time, and its stored bodies.
Shared by `mirror runs`, `mirror trace` and the portal's Runs screens."""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel, Field

from mirrordimensions.errors import MirrorError
from mirrordimensions.hostos.lock import ProjectLock
from mirrordimensions.project import Project
from mirrordimensions.service.runs import load_result, run_dir
from mirrordimensions.trace import access, summary, timeline
from mirrordimensions.trace import steps as steps_mod

PAGE = 500
MAX_PAGE = 2000


class RunSummary(BaseModel):
    run_id: str
    scenario: str | None
    agent: str | None
    status: str
    isolation: str | None
    coverage: str
    suspected: bool
    started: str | None
    checks_passed: int
    checks: int
    live: bool = Field(description="Still running: it has events but no result yet")


class EventPage(BaseModel):
    run_id: str
    total: int = Field(description="Events matching the filter")
    offset: int
    events: list[dict[str, Any]]
    start: str | None = None


def running(project: Project) -> bool:
    """Whether a run is in progress now: one holds the project's run lock. A run that has
    no result but whose process is gone (it crashed) did not finish, and is not live."""
    return ProjectLock(project.state_dir, "run").held() is not None


def _summary(folder: Path, active: bool = False) -> RunSummary:
    result_path = folder / "result.json"
    data: dict[str, Any] = {}
    if result_path.is_file():
        try:
            data = json.loads(result_path.read_text(encoding="utf-8"))
        except ValueError:
            data = {}
    first: dict[str, Any] = {}
    events = folder / "events.jsonl"
    if events.is_file():
        with events.open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    item = json.loads(line)
                except ValueError:
                    continue
                if item.get("type") == "run.start":
                    first = item
                    break
    start = cast(dict[str, Any], first.get("data") or {})
    checks = cast(list[dict[str, Any]], data.get("checks") or [])
    live = not data and events.is_file() and active
    return RunSummary(
        run_id=folder.name,
        scenario=data.get("scenario") or start.get("scenario"),
        agent=data.get("agent") or start.get("agent"),
        status=str(data.get("status") or ("running" if live else "unfinished")),
        isolation=data.get("isolation"),
        coverage=str(
            cast(dict[str, Any], data.get("coverage") or {}).get(
                "status", "unknown" if data else "pending"
            )
        ),
        suspected=bool(data.get("suspected")),
        started=first.get("ts"),
        checks_passed=sum(1 for c in checks if c.get("passed")),
        checks=len(checks),
        live=live,
    )


def list_runs(project: Project) -> list[RunSummary]:
    """Every run, newest first."""
    folder = project.state_dir / "runs"
    if not folder.is_dir():
        return []
    current = current_run(project)
    found = [
        _summary(p, active=p.name == current)
        for p in folder.glob("r_*")
        if (p / "events.jsonl").is_file()
    ]
    return sorted(found, key=lambda r: (r.started or "", r.run_id), reverse=True)


def current_run(project: Project) -> str | None:
    """The run in progress: while a run holds the lock, the newest run with no result.
    Runs go one at a time, so no other run without a result can still be going."""
    if not running(project):
        return None
    folder = project.state_dir / "runs"
    unfinished = [
        p
        for p in folder.glob("r_*")
        if (p / "events.jsonl").is_file() and not (p / "result.json").is_file()
    ]
    if not unfinished:
        return None
    return max(unfinished, key=lambda p: (p / "events.jsonl").stat().st_mtime).name


def _newest_unfinished(project: Project, folder: Path) -> bool:
    return current_run(project) == folder.name


def get_result(project: Project, run_id: str) -> dict[str, Any]:
    return load_result(project, run_id).model_dump(mode="json", exclude_none=True)


def read_events(
    project: Project,
    run_id: str,
    keep: timeline.Filter | None = None,
    offset: int = 0,
    limit: int = PAGE,
    around: int | None = None,
) -> EventPage:
    """One page of the run's timeline, each event with its one-line summary. `around` asks
    for the page that holds the event with that sequence number."""
    folder = run_dir(project, run_id)
    found = timeline.load(folder / "events.jsonl")
    matching = [e for e in found.events if keep is None or keep(e)]
    limit = max(1, min(limit, MAX_PAGE))
    if around is not None:
        index = next((i for i, e in enumerate(matching) if e.get("seq") == around), None)
        if index is not None:
            offset = (index // limit) * limit
    page = matching[offset : offset + limit]
    return EventPage(
        run_id=folder.name,
        total=len(matching),
        offset=offset,
        events=[shown(e, found.start) for e in page],
        start=found.start.isoformat() if found.start else None,
    )


def shown(event: dict[str, Any], start: Any) -> dict[str, Any]:
    return {
        **event,
        "summary": summary.summarize(event, full_hosts=True),
        "at": summary.elapsed(event, start),
    }


def follow_events(
    project: Project, run_id: str, keep: timeline.Filter | None = None
) -> Iterator[dict[str, Any]]:
    """Events as they are written, from the first, until the run ends."""
    folder = run_dir(project, run_id)
    start = None
    for event in timeline.follow(folder / "events.jsonl"):
        if start is None and event.get("type") == "run.start":
            start = timeline.parse_ts(event)
        if keep is None or keep(event):
            yield shown(event, start or timeline.parse_ts(event))


def read_body(project: Project, run_id: str, ref: str) -> tuple[bytes, str]:
    """A stored request, response or model exchange, by the ref an event names
    (`bodies/<name>` or `model/<name>`), with a content type for display."""
    folder = run_dir(project, run_id)
    parts = ref.split("/")
    if len(parts) != 2 or parts[0] not in ("bodies", "model") or parts[1] in ("", ".", ".."):
        raise MirrorError(
            f"{ref!r} is not a stored body.", "Bodies are named bodies/<name> or model/<name>.", ""
        )
    path = folder / parts[0] / parts[1]
    if not path.is_file():
        raise MirrorError(
            f"Run {run_id} has no {ref}.",
            "The run kept no body by that name (empty bodies are not stored).",
            "",
        )
    data = path.read_bytes()
    kind = "application/json" if data[:1] in (b"{", b"[") else "text/plain"
    return data, kind


def wait_for_run(project: Project, run_id: str, timeout: float = 30.0) -> Path:
    """The folder of a run that was just started, once its first event is written."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            return run_dir(project, run_id)
        except MirrorError:
            time.sleep(0.2)
    raise MirrorError(
        f"Run {run_id} did not start within {int(timeout)} s.",
        "Its first event was never written.",
        "See the portal's terminal for the error, or run it with: mirror run",
    )


# -- steps: the live view and `mirror watch` -------------------------------------------


class PlaceResource(BaseModel):
    place: str = Field(description="`repo:<owner>/<name>` or `channel:<name>`")
    label: str
    granted: bool


class Place(BaseModel):
    system: str
    label: str
    kind: str = Field(description="`system`, `model` or `outside`")
    resources: list[PlaceResource]


class StepsView(BaseModel):
    run_id: str
    live: bool
    agents: list[str]
    places: list[Place] = Field(description="The map: granted systems and those touched")
    steps: list[steps_mod.Step]


def _run_start(folder: Path) -> dict[str, Any]:
    events = folder / "events.jsonl"
    if events.is_file():
        with events.open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    item = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(item, dict):
                    continue
                event = cast(dict[str, Any], item)
                if event.get("type") == "run.start":
                    return cast(dict[str, Any], event.get("data") or {})
    return {}


def step_context(project: Project, run_id: str) -> tuple[steps_mod.Context, list[Place]]:
    """Whose events a run's are and where each host is, read against the project's plan,
    with the map's places: every system the agent is granted, with its resources."""
    from mirrordimensions.service import agents as agents_svc
    from mirrordimensions.service.environment import system_label
    from mirrordimensions.service.runs import agent_clients, grants_for
    from mirrordimensions.service.sandbox import world_plan
    from mirrordimensions.twins.base import get_twin
    from mirrordimensions.twins.profile import profile_of

    folder = run_dir(project, run_id)
    start = _run_start(folder)
    name = str(start.get("agent") or "agent")
    plan = world_plan(project)
    systems: dict[str, steps_mod.System] = {}
    for app in plan.apps:
        twin = get_twin(app.product)
        systems[app.hostname.lower()] = steps_mod.System(
            id=app.id,
            label=system_label(app.kind, app.product, app.id),
            table=profile_of(twin.product).table if twin is not None else None,
            mcp=app.is_mcp,
        )
    clients = {str(c) for c in cast(list[Any], start.get("clients") or [])}
    grants: list[access.Grant] = []
    try:
        agent, _ = agents_svc.load_agent(project, name)
        if not clients:  # recorded before run.start named them
            clients = agent_clients(plan, agent, servers=False)
        world = agents_svc._world(project)  # pyright: ignore[reportPrivateUsage]
        grants = grants_for(plan, agent, world.org)
    except MirrorError:
        pass  # the agent's file is gone: its steps still read, its map shows what it touched
    by_id = {s.id: s for s in systems.values()}
    places: list[Place] = []
    for grant in grants:
        system = by_id.get(grant.system)
        if system is None:
            continue
        owned: list[PlaceResource] = []
        for repo in sorted(grant.repos or {}):
            full = repo if "/" in repo else f"{grant.owner}/{repo}"
            owned.append(
                PlaceResource(place=f"repo:{full}", label=repo.split("/")[-1], granted=True)
            )
        for channel in grant.channels or []:
            owned.append(
                PlaceResource(place=f"channel:{channel}", label=f"#{channel}", granted=True)
            )
        places.append(Place(system=system.id, label=system.label, kind="system", resources=owned))

    def body(ref: str) -> bytes:
        try:
            return read_body(project, folder.name, ref)[0]
        except MirrorError:
            return b""

    ctx = steps_mod.Context(
        agent=name,
        clients=clients,
        systems=systems,
        model_hosts=set(plan.model_hosts),
        body=body,
    )
    return ctx, places


def _with_touched(
    places: list[Place], ctx: steps_mod.Context, found: list[steps_mod.Step]
) -> list[Place]:
    """Add the systems and resources the steps reached that no grant named."""
    by_system = {p.system: p for p in places}
    labels = {s.id: s.label for s in ctx.systems.values()}
    for step in found:
        where = step.location
        if where.system in (steps_mod.AGENT,):
            continue
        place = by_system.get(where.system)
        if place is None:
            kind = (
                where.system if where.system in (steps_mod.MODEL, steps_mod.OUTSIDE) else "system"
            )
            label = labels.get(where.system, where.label)
            if kind == steps_mod.MODEL:
                label = "Model API"
            elif kind == steps_mod.OUTSIDE:
                label = "Outside the sandbox"
            place = Place(system=where.system, label=label, kind=kind, resources=[])
            by_system[where.system] = place
            places.append(place)
        if where.place and all(r.place != where.place for r in place.resources):
            place.resources.append(
                PlaceResource(
                    place=where.place, label=steps_mod.place_label(where.place), granted=False
                )
            )
    return places


def read_steps(project: Project, run_id: str) -> StepsView:
    """The run's steps so far, with the map they move on."""
    ctx, places = step_context(project, run_id)
    folder = run_dir(project, run_id)
    found = steps_mod.steps_of(timeline.load(folder / "events.jsonl").events, ctx)
    return StepsView(
        run_id=folder.name,
        live=not (folder / "result.json").is_file() and _newest_unfinished(project, folder),
        agents=[ctx.agent],
        places=_with_touched(places, ctx, found),
        steps=found,
    )


def follow_steps(project: Project, run_id: str) -> Iterator[steps_mod.Step]:
    """Each step as it opens and each time it grows, from the first, until the run ends.
    A step that changes is sent again with the same index."""
    ctx, _ = step_context(project, run_id)
    folder = run_dir(project, run_id)
    return steps_mod.follow_steps(timeline.follow(folder / "events.jsonl"), ctx)
