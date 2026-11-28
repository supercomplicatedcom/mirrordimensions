# SPDX-License-Identifier: Apache-2.0
"""One ordered timeline from every event source of a run.

The collector records events from all sources (gateway, model, MCP, DNS, egress, browser,
host, runner, state and evaluator) into one `events.jsonl` as they arrive, each with a
host-side timestamp and a sequence number. This module reads it back, checks each line
against the event schema, and orders by timestamp, then sequence number, so the order is
stable however the file was written. Sequence numbers are kept: results refer to them.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from pydantic import ValidationError

from mirrordimensions.config.events import EVENT_TYPES, Event


@dataclass
class Timeline:
    events: list[dict[str, Any]]
    # Lines that are not events, or not valid ones: (line number, reason). Kept so a
    # damaged file is reported rather than silently shortened.
    problems: list[tuple[int, str]] = field(default_factory=list[tuple[int, str]])

    @property
    def start(self) -> datetime | None:
        for e in self.events:
            if e.get("type") == "run.start":
                return parse_ts(e)
        return parse_ts(self.events[0]) if self.events else None


def parse_ts(event: dict[str, Any]) -> datetime | None:
    try:
        return datetime.fromisoformat(str(event.get("ts", "")).replace("Z", "+00:00"))
    except ValueError:
        return None


def _check(raw: Any) -> tuple[dict[str, Any] | None, str]:
    if not isinstance(raw, dict):
        return None, "not a JSON object"
    event = cast(dict[str, Any], raw)
    kind = str(event.get("type", ""))
    if event.get("source") == "gateway" and kind.startswith(("model.", "mcp.")):
        # Runs recorded before model calls and MCP messages had sources of their own.
        event["source"] = kind.split(".", 1)[0]
    try:
        Event.model_validate(event)
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(p) for p in first.get("loc", ())) or "event"
        return event, f"{where}: {first.get('msg', 'invalid')}"
    return event, ""


def parse_lines(lines: Iterable[str]) -> Timeline:
    events: list[dict[str, Any]] = []
    problems: list[tuple[int, str]] = []
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except ValueError:
            problems.append((number, "not JSON"))
            continue
        event, problem = _check(raw)
        if problem:
            problems.append((number, problem))
        if event is not None and "seq" in event and "ts" in event:
            events.append(event)
    events.sort(key=lambda e: (str(e["ts"]), int(e["seq"])))
    return Timeline(events, problems)


def load(path: Path) -> Timeline:
    """The timeline of the run whose `events.jsonl` is at `path`."""
    if not path.is_file():
        return Timeline([])
    return parse_lines(path.read_text(encoding="utf-8").splitlines())


def follow(
    path: Path, *, stop: Callable[[], bool] | None = None, poll: float = 0.25
) -> Iterator[dict[str, Any]]:
    """Events as they are written, until the run ends (`run.end`) or `stop()` is true."""
    offset = 0
    pending = ""
    while True:
        if path.is_file():
            with path.open("r", encoding="utf-8", newline="\n") as handle:
                handle.seek(offset)
                chunk = handle.read()
                offset = handle.tell()
            pending += chunk
            *lines, pending = pending.split("\n")
            for line in lines:
                try:
                    raw = json.loads(line)
                except ValueError:
                    continue
                if isinstance(raw, dict):
                    event = cast(dict[str, Any], raw)
                    yield event
                    if event.get("type") == "run.end":
                        return
        if stop is not None and stop():
            return
        time.sleep(poll)


@dataclass(frozen=True)
class Filter:
    """Which events to keep. Empty sets keep everything; `text` matches anywhere in the
    event, ignoring case."""

    sources: frozenset[str] = frozenset()
    types: frozenset[str] = frozenset()
    text: str = ""

    def __call__(self, event: dict[str, Any]) -> bool:
        if self.sources and event.get("source") not in self.sources:
            return False
        if self.types and not any(_type_matches(str(event.get("type", "")), t) for t in self.types):
            return False
        return not self.text or self.text.lower() in json.dumps(event).lower()


def _type_matches(kind: str, wanted: str) -> bool:
    """`http.exchange` matches itself; `browser` or `browser.*` matches every browser type."""
    stem = wanted.removesuffix(".*")
    return kind == wanted or kind.startswith(stem + ".")


SOURCES = tuple(EVENT_TYPES)


def unknown(values: Iterable[str], known: Iterable[str]) -> list[str]:
    """The values that name nothing, for an actionable error."""
    known_set = set(known)
    return [v for v in values if v.removesuffix(".*") not in known_set]


def all_types() -> set[str]:
    out: set[str] = set()
    for kinds in EVENT_TYPES.values():
        out |= kinds
        out |= {k.split(".", 1)[0] for k in kinds}
    return out
