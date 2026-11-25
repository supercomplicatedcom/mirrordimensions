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
from mirrordimensions.project import Project
from mirrordimensions.service.runs import load_result, run_dir
from mirrordimensions.trace import summary, timeline

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


def _summary(folder: Path) -> RunSummary:
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
    return RunSummary(
        run_id=folder.name,
        scenario=data.get("scenario") or start.get("scenario"),
        agent=data.get("agent") or start.get("agent"),
        status=str(data.get("status") or "running"),
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
        live=not data and events.is_file(),
    )


def list_runs(project: Project) -> list[RunSummary]:
    """Every run, newest first."""
    folder = project.state_dir / "runs"
    if not folder.is_dir():
        return []
    found = [_summary(p) for p in folder.glob("r_*") if (p / "events.jsonl").is_file()]
    return sorted(found, key=lambda r: (r.started or "", r.run_id), reverse=True)


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
