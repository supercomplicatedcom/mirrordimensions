# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""The run event: one JSON object per line of `.mirror/runs/<run-id>/events.jsonl`."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Literal, Self

from pydantic import Field, model_validator

from mirrordimensions.config.common import StrictModel

Source = Literal[
    "runner", "gateway", "model", "dns", "egress", "browser", "host", "state", "evaluator", "mcp"
]

EVENT_TYPES: dict[str, frozenset[str]] = {
    "runner": frozenset(
        {
            "run.start",
            "snapshot.restored",
            "overlay.applied",
            "work.delivered",
            "agent.woken",
            "run.end",
        }
    ),
    "gateway": frozenset({"http.exchange", "tls.handshake", "route.unknown_host", "rule.applied"}),
    "model": frozenset({"model.request", "model.response"}),
    "dns": frozenset({"dns.query"}),
    "egress": frozenset({"egress.blocked"}),
    "browser": frozenset({"browser.navigate", "browser.action", "browser.screenshot"}),
    "host": frozenset({"process.exec"}),
    "state": frozenset({"state.diff"}),
    "evaluator": frozenset({"check.result", "side_effect.unexpected", "suspicion.flag"}),
    "mcp": frozenset({"mcp.message", "mcp.call"}),
}


class Event(StrictModel):
    seq: int = Field(ge=0)
    ts: datetime = Field(description="UTC, from the engine's clock")
    run_id: str = Field(pattern=r"^r_[a-z0-9]{4,32}$")
    source: Source
    type: str
    actor: str | None = None
    data: dict[str, Any] = Field(default_factory=dict[str, Any])
    org: str | None = Field(default=None, description="Empty when self-hosted")
    user: str | None = Field(default=None, description="Empty when self-hosted")

    @model_validator(mode="after")
    def _type_matches_source(self) -> Self:
        allowed = EVENT_TYPES[self.source]
        if self.type not in allowed:
            raise ValueError(
                f"event type {self.type!r} is not a {self.source} event "
                f"(expected one of: {', '.join(sorted(allowed))})"
            )
        if self.ts.utcoffset() != timedelta(0):
            raise ValueError("ts must be in UTC")
        return self
