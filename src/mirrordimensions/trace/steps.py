# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""A run's events grouped into steps, for the live view and `mirror watch` (build spec,
"Live view requirements").

Every event the agent caused is given a location (a system and, where possible, a resource
inside it) and a plain sentence. Both come from the system's profile (`locate`, `describe`),
never from a model, so they are deterministic and free. The gateway records them with each
exchange as it captures it; for runs recorded before it did, they are worked out here from
the method and path.

Consecutive requests to the same resource within two seconds become one step, and a model
call is its own step. A step is published as soon as its first event arrives and again
each time it grows, so a live view never waits for a step to close.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, cast

from pydantic import BaseModel, Field

from mirrordimensions.network.payloads.behavior import Located, SurfaceTable
from mirrordimensions.trace.timeline import parse_ts

StepKind = Literal["request", "think", "blocked", "violation", "info", "end"]
MERGE_S = 2.0
REFUSED = (401, 403)
FAILED_LOOKUPS = ("NXDOMAIN", "REFUSED", "SERVFAIL")
AGENT = "agent"  # where the agent is before work arrives and after the run ends
MODEL = "model"
OUTSIDE = "outside"
# Surfaces a page loads by itself (styles, pictures, its live connection): part of the step
# that opened the page, not steps of their own.
FOLDED = ("asset", "background")


class Location(BaseModel):
    system: str = Field(description="An app id, or `agent`, `model` or `outside`")
    resource: str | None = Field(default=None, description="The exact resource, if named")
    place: str | None = Field(
        default=None, description="The map's resource: a repository or channel"
    )
    label: str = Field(description="Where, in plain words: `Code hosting, billing-service`")


class Step(BaseModel):
    index: int
    start: str
    end: str
    at: str = Field(description="Time since the run started: `01:04.2`")
    agent: str
    location: Location
    kind: StepKind
    sentence: str
    detail: str = ""
    events: list[int]
    requests: int = Field(default=0, description="Requests and tool calls it covers")


@dataclass(frozen=True)
class System:
    id: str
    label: str
    table: SurfaceTable | None = None  # None: a system without a profile (stand-in or MCP)
    mcp: bool = False


@dataclass
class Context:
    """What a run's events are read against: whose events they are and where each host is."""

    agent: str
    clients: set[str]
    systems: dict[str, System]  # host -> system
    model_hosts: set[str] = field(default_factory=set[str])
    # A stored body by the ref an event names, for runs recorded before the gateway located
    # each exchange itself: the request names a resource, responses name ids.
    body: Callable[[str], bytes] | None = None


def place_of(resource: str | None) -> str | None:
    """The map's resource for an exact one: a file or issue sits in its repository."""
    if not resource or ":" not in resource:
        return None
    kind, _, rest = resource.partition(":")
    if kind in ("repo", "file", "issue", "pull", "branch", "comment"):
        parts = rest.replace("#", "/").split("/")
        return f"repo:{parts[0]}/{parts[1]}" if len(parts) >= 2 else None
    if kind == "channel" and not _looks_like_id(rest):
        return resource
    return None


def _looks_like_id(text: str) -> bool:
    return len(text) == 26 and text.isalnum() and text.islower()


def place_label(place: str) -> str:
    kind, _, rest = place.partition(":")
    if kind == "repo":
        return rest.split("/", 1)[-1]
    if kind == "channel":
        return f"#{rest}"
    return rest


def _elapsed(at: datetime | None, start: datetime | None) -> str:
    if at is None or start is None:
        return "--:--.-"
    seconds = max(0.0, (at - start).total_seconds())
    minutes, rest = divmod(seconds, 60)
    return f"{int(minutes):02d}:{rest:04.1f}"


def _is_request(event: dict[str, Any]) -> int:
    return 1 if event.get("type") in ("http.exchange", "mcp.call") else 0


def _host(data: dict[str, Any]) -> str:
    return str(data.get("host") or "").split(":")[0].lower()


@dataclass
class _Open:
    step: Step
    last: datetime | None
    key: tuple[str, ...]


class Stepper:
    """Feed events in order; each call returns the steps it opened or changed."""

    def __init__(self, ctx: Context) -> None:
        self.ctx = ctx
        self.steps: list[Step] = []
        self.start: datetime | None = None
        self.open: _Open | None = None
        self.by_event: dict[int, int] = {}  # event seq -> step index
        self.names: dict[str, dict[str, str]] = {}  # system -> names learned from responses

    # -- building steps -------------------------------------------------------------

    def _location(self, system: str, resource: str | None = None) -> Location:
        place = place_of(resource)
        if system == AGENT:
            label = "Waiting for work"
        elif system == MODEL:
            label = "Model API"
        elif system == OUTSIDE:
            label = "Outside the sandbox"
        else:
            known = next((s for s in self.ctx.systems.values() if s.id == system), None)
            label = known.label if known else system
            if place:
                label = f"{label}, {place_label(place)}"
        return Location(system=system, resource=resource, place=place, label=label)

    def _emit(
        self,
        event: dict[str, Any],
        kind: StepKind,
        where: Location,
        sentence: str,
        detail: str = "",
        merge: tuple[str, ...] | None = None,
    ) -> Step:
        at = parse_ts(event)
        seq = int(event.get("seq", 0))
        current = self.open
        if (
            merge is not None
            and current is not None
            and current.key == merge
            and at is not None
            and current.last is not None
            and (at - current.last).total_seconds() <= MERGE_S
        ):
            step = current.step
            step.events.append(seq)
            step.requests += _is_request(event)
            step.end = str(event.get("ts"))
            current.last = at
            extra = len(step.events) - 1
            first = step.detail.split(" (and ", 1)[0]
            step.detail = f"{first} (and {extra} more)" if extra else first
            self.by_event[seq] = step.index
            return step
        step = Step(
            index=len(self.steps),
            start=str(event.get("ts")),
            end=str(event.get("ts")),
            at=_elapsed(at, self.start),
            agent=self.ctx.agent,
            location=where,
            kind=kind,
            sentence=sentence,
            detail=detail,
            events=[seq],
            requests=_is_request(event),
        )
        self.steps.append(step)
        self.by_event[seq] = step.index
        self.open = _Open(step, at, merge) if merge is not None else None
        return step

    def feed(self, event: dict[str, Any]) -> list[Step]:
        kind = str(event.get("type", ""))
        data: dict[str, Any] = event.get("data") or {}
        mine = data.get("client") in self.ctx.clients or data.get("src") in self.ctx.clients
        match kind:
            case "run.start":
                self.start = parse_ts(event)
                return []
            case "work.delivered":
                channel = str(data.get("channel", "")).split(".", 1)[-1].replace("_", " ")
                who = f" from {data['from']}" if data.get("from") else ""
                return [
                    self._emit(event, "info", self._location(AGENT), "Work arrives", channel + who)
                ]
            case "run.end":
                status = str(data.get("status", "ended"))
                return [self._emit(event, "end", self._location(AGENT), f"Run ended: {status}", "")]
            case "http.exchange" if mine:
                return self._exchange(event, data)
            case "model.exchange" if self._model_mine(data):
                tokens = ""
                if "input_tokens" in data:
                    tokens = f", {data.get('input_tokens')} in / {data.get('output_tokens')} out"
                seconds = float(data.get("duration_ms") or 0) / 1000
                detail = f"{data.get('model') or 'model'}{tokens}, {seconds:.1f} s"
                return [self._emit(event, "think", self._location(MODEL), "Thinks", detail)]
            case "model.refused":
                return [
                    self._emit(
                        event,
                        "blocked",
                        self._location(MODEL),
                        "A model call is refused",
                        str(data.get("reason", "")),
                        merge=("refused", MODEL),
                    )
                ]
            case "mcp.call" if mine:
                system = self.ctx.systems.get(_host(data))
                where = self._location(system.id if system else _host(data), data.get("resource"))
                blocked = bool(data.get("is_error"))
                sentence = str(data.get("sentence") or f"Calls {data.get('tool')}")
                return [
                    self._emit(
                        event,
                        "blocked" if blocked else "request",
                        where,
                        sentence,
                        f"tool {data.get('tool')}" + (" (refused)" if blocked else ""),
                        merge=("mcp", where.system, str(where.resource), sentence),
                    )
                ]
            case "dns.query" if mine and str(data.get("rcode")) in FAILED_LOOKUPS:
                name = str(data.get("name", "")).rstrip(".")
                return [
                    self._emit(
                        event,
                        "blocked",
                        self._location(OUTSIDE),
                        f"Looks up {name}",
                        f"The lookup fails ({data.get('rcode')}). Nothing left the sandbox.",
                        merge=("dns", name),
                    )
                ]
            case "egress.blocked" if mine:
                to = (
                    f"{data.get('dst')}:{data.get('dport')}"
                    if data.get("dport")
                    else data.get("dst")
                )
                return [
                    self._emit(
                        event,
                        "blocked",
                        self._location(OUTSIDE),
                        f"Tries to connect to {to}",
                        f"Blocked ({data.get('proto', 'IP')}). Nothing left the sandbox.",
                        merge=("egress", str(to)),
                    )
                ]
            case "route.unknown_host" if mine:
                name = data.get("host") or data.get("sni") or "an unknown host"
                return [
                    self._emit(
                        event,
                        "blocked",
                        self._location(OUTSIDE),
                        f"Tries to reach {name}",
                        "No such system. Nothing left the sandbox.",
                        merge=("route", str(name)),
                    )
                ]
            case "check.result" if data.get("kind") == "forbidden" and not data.get("passed"):
                return self._violation(event, data)
            case "side_effect.unexpected":
                system = str(data.get("system", ""))
                obj = str(data.get("object", ""))
                where = self._location(system, obj.split("/issue:")[0] if obj else None)
                return [
                    self._emit(
                        event,
                        "violation",
                        where,
                        "Changes something it was not asked to",
                        f"{obj} ({data.get('change')})",
                    )
                ]
            case _:
                return []

    def _model_mine(self, data: dict[str, Any]) -> bool:
        client = data.get("client")
        return client is None or client in self.ctx.clients

    def _exchange(self, event: dict[str, Any], data: dict[str, Any]) -> list[Step]:
        host = _host(data)
        if host in self.ctx.model_hosts:
            return []  # its model.exchange is the step
        system = self.ctx.systems.get(host)
        if system is None:
            where = self._location(OUTSIDE)
            return [
                self._emit(
                    event,
                    "blocked",
                    where,
                    f"Tries to reach {host}",
                    "No such system.",
                    merge=("route", host),
                )
            ]
        if system.mcp:
            return []  # its mcp.call events are the steps
        located = self._locate(system, data)
        status = data.get("status")
        refused = isinstance(status, int) and status in REFUSED
        path = str(data.get("path", "")).split("?")[0]
        detail = f"{data.get('method')} {path}  {status if status is not None else 'no answer'}"
        if located.kind in FOLDED and self.open is not None:
            step = self.open.step
            if step.location.system == system.id and step.kind == "request":
                return [
                    self._emit(
                        event, "request", step.location, step.sentence, detail, merge=self.open.key
                    )
                ]
        where = self._location(system.id, located.resource)
        sentence = located.sentence + (" (refused)" if refused else "")
        # Reads of one resource merge; a change is a step of its own, so a write is never
        # hidden inside the reads before it (consecutive identical changes still merge).
        writes = located.access in ("write", "admin") or str(data.get("method")) != "GET"
        key = (
            "http",
            system.id,
            str(located.resource or located.surface),
            str(refused),
            located.sentence if writes else "read",
        )
        return [
            self._emit(
                event, "blocked" if refused else "request", where, sentence, detail, merge=key
            )
        ]

    def _locate(self, system: System, data: dict[str, Any]) -> Located:
        recorded = cast(dict[str, Any], data.get("where") or {})
        if recorded.get("surface"):
            resource, access = recorded.get("resource"), recorded.get("access")
            return Located(
                surface=str(recorded["surface"]),
                resource=str(resource) if resource else None,
                access=str(access) if access else None,
                sentence=str(recorded.get("sentence") or ""),
                kind=str(recorded.get("kind") or "endpoint"),
            )
        if system.table is None:
            path = str(data.get("path", "")).split("?")[0]
            return Located("unknown", None, None, f"{data.get('method')} {path}", "unknown")
        method, path = str(data.get("method")), str(data.get("path", ""))
        read = self.ctx.body
        names = self.names.setdefault(system.id, {})
        request = read(str(data["req_body_ref"])) if read and data.get("req_body_ref") else b""
        located = system.table.locate(method, path, request, names)
        status = data.get("status")
        if read and data.get("resp_body_ref") and isinstance(status, int) and status < 300:
            names.update(system.table.learn(method, path, read(str(data["resp_body_ref"]))))
        return located

    def _violation(self, event: dict[str, Any], data: dict[str, Any]) -> list[Step]:
        evidence = str(data.get("evidence") or "")
        rule = f"This breaks a forbidden check: {evidence}" if evidence else "This breaks a rule."
        index = self.by_event.get(int(data.get("event") or -1))
        if index is not None:
            step = self.steps[index]
            step.kind = "violation"
            step.detail = f"{step.detail}. {rule}" if step.detail else rule
            step.events.append(int(event.get("seq", 0)))
            return [step]
        return [
            self._emit(
                event, "violation", self._location(AGENT), f"Breaks {data.get('check')}", rule
            )
        ]


def steps_of(events: Iterable[dict[str, Any]], ctx: Context) -> list[Step]:
    """Every step of a finished run."""
    stepper = Stepper(ctx)
    for event in events:
        stepper.feed(event)
    return stepper.steps


def follow_steps(events: Iterable[dict[str, Any]], ctx: Context) -> Iterator[Step]:
    """Each step as it opens and again each time it changes (same index, more events)."""
    stepper = Stepper(ctx)
    for event in events:
        yield from (s.model_copy(deep=True) for s in stepper.feed(event))
