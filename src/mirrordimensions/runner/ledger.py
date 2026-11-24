# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""The touch ledger, `ledger.json` (build spec, "What the agent touched and what the model
saw are different lists").

One row per resource: who touched it (the agent, the model, or both), how (listed, read,
written, deleted, denied), the first and last event, and the events as evidence.

- The agent touches a resource when it requests it: each exchange is located with the
  system's profile (`locate`), and every resource a response carried is listed (`exposed`):
  a search that returns thirty issues lists thirty issues.
- MCP tool calls name their resource and access themselves (`mcp.call`).
- The model sees a resource when text the agent received from it appears in a model request.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from mirrordimensions.network.payloads.behavior import SurfaceTable

MIN_SNIPPET = 24  # characters of received text that must reappear for "the model saw it"


@dataclass
class Row:
    resource: str
    system: str
    agent: set[str] = field(default_factory=set[str])
    model: bool = False
    events: list[int] = field(default_factory=list[int])

    def as_dict(self) -> dict[str, Any]:
        who = "both" if self.agent and self.model else ("model" if self.model else "agent")
        return {
            "resource": self.resource,
            "system": self.system,
            "who": who,
            "how": sorted(self.agent | ({"seen by model"} if self.model else set())),
            "first": min(self.events),
            "last": max(self.events),
            "events": sorted(set(self.events)),
        }


def _how(method: str, access: str | None, status: int | None) -> str:
    if status is not None and status >= 400:
        return "denied"
    if method == "DELETE":
        return "deleted"
    if access in ("write", "admin") or method in ("POST", "PUT", "PATCH"):
        return "written"
    return "read"


def _snippets(body: bytes) -> list[str]:
    """Distinctive text a response carried: long string values (titles, bodies, file text)."""
    try:
        data = json.loads(body or b"null")
    except ValueError:
        text = body.decode("utf-8", "replace")
        return [text[:200]] if len(text) >= MIN_SNIPPET else []
    out: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, str) and len(value) >= MIN_SNIPPET and " " in value:
            out.append(value[:200])
        elif isinstance(value, dict):
            for v in value.values():  # pyright: ignore[reportUnknownVariableType]
                walk(v)
        elif isinstance(value, list):
            for v in value:  # pyright: ignore[reportUnknownVariableType]
                walk(v)

    walk(data)
    return out


def build(
    events: list[dict[str, Any]],
    clients: set[str],
    tables: dict[str, tuple[str, SurfaceTable]],
    body: Callable[[str | None], bytes],
    model_hosts: set[str],
) -> list[dict[str, Any]]:
    """`tables`: host -> (app id, the system's surfaces); `body(ref)`: a captured body;
    `model_hosts`: hosts whose requests are model requests."""
    rows: dict[str, Row] = {}
    texts: dict[str, list[str]] = {}

    def row(resource: str, system: str) -> Row:
        return rows.setdefault(resource, Row(resource=resource, system=system))

    model_requests: list[tuple[int, str]] = []
    for e in events:
        data = e.get("data", {})
        seq = int(e.get("seq", 0))
        if e.get("type") == "mcp.call" and data.get("client") in clients:
            resource = data.get("resource") or f"tool:{data.get('tool')}"
            how = (
                "denied"
                if data.get("is_error")
                else ("written" if data.get("access") in ("write", "admin") else "read")
            )
            r = row(resource, str(data.get("host", "")))
            r.agent.add(how)
            r.events.append(seq)
            continue
        if e.get("type") != "http.exchange" or data.get("client") not in clients:
            continue
        host = str(data.get("host", "")).split(":")[0]
        if host in model_hosts:
            if data.get("req_body_ref"):
                model_requests.append(
                    (seq, body(data.get("req_body_ref")).decode("utf-8", "replace"))
                )
            continue
        if host not in tables:
            continue  # an MCP server: its tool calls are rows of their own (mcp.call)
        system, table = tables[host]
        method, path, status = (
            str(data.get("method")),
            str(data.get("path", "")).split("?")[0],
            data.get("status"),
        )
        located = table.locate(method, path)
        resource = located.resource or f"{system}:{located.surface}"
        r = row(resource, system)
        r.agent.add(_how(method, located.access, status))
        r.events.append(seq)
        if method == "GET" and status == 200:
            received = body(data.get("resp_body_ref"))
            texts.setdefault(resource, []).extend(_snippets(received))
            for listed in table.exposed(method, path, received):
                if listed != resource:
                    lr = row(listed, system)
                    lr.agent.add("listed")
                    lr.events.append(seq)
    for seq, text in model_requests:
        for resource, snippets in texts.items():
            if any(s in text for s in snippets):
                rows[resource].model = True
                rows[resource].events.append(seq)
    return [r.as_dict() for r in sorted(rows.values(), key=lambda r: (min(r.events), r.resource))]
