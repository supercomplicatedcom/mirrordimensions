# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""Reconcile the `mcp` coverage channel against the gateway's own record (CLAUDE.md: a new
way to touch something needs a reconciliation test).

Two independent records cover a tool call: the agent's exchange with the MCP server, and the
server's own exchanges with the twins, both captured at the gateway. They must agree:

1. every exchange with an MCP server's endpoint carries at least one `mcp.message`;
2. every tool call that succeeded with write access is matched by a write from that MCP
   server to a twin, made while the call was in progress (before its exchange was recorded,
   after the previous one from the same client).
"""

from __future__ import annotations

from typing import Any

WRITES = ("POST", "PUT", "PATCH", "DELETE")


def reconcile(
    events: list[dict[str, Any]],
    mcp_hosts: set[str],
    front_ips: set[str],
    endpoints: set[str] | None = None,
) -> list[str]:
    """Problems found; empty when the two records agree. With `endpoints`, only exchanges
    with those paths are MCP exchanges (an exposed server also serves its sign-in)."""
    problems: list[str] = []
    exchanges = {
        e["data"].get("gateway_seq"): e
        for e in events
        if e.get("type") == "http.exchange"
        and str(e["data"].get("host", "")).split(":")[0] in mcp_hosts
        and e["data"].get("method") == "POST"
        and (endpoints is None or str(e["data"].get("path", "")).split("?")[0] in endpoints)
    }
    carried = {e["data"].get("exchange") for e in events if e.get("type") == "mcp.message"}
    for seq, exchange in exchanges.items():
        if seq not in carried:
            problems.append(f"exchange {seq} with {exchange['data']['host']} has no mcp.message")
    previous_end: dict[str, int] = {}
    order = {
        e["data"].get("gateway_seq"): i
        for i, e in enumerate(events)
        if "gateway_seq" in e.get("data", {})
    }
    for event in events:
        if event.get("type") != "mcp.call":
            continue
        data = event["data"]
        if data.get("access") not in ("write", "admin") or data.get("is_error"):
            continue
        end = order.get(data.get("exchange"), -1)
        start = previous_end.get(data.get("client", ""), -1)
        writes = [
            e
            for e in events[start + 1 : end]
            if e.get("type") == "http.exchange"
            and e["data"].get("client") in front_ips
            and e["data"].get("method") in WRITES
        ]
        if not writes:
            problems.append(f"{data.get('tool')} succeeded but no write reached a system")
        previous_end[data.get("client", "")] = end
    return problems


def unexplained_writes(events: list[dict[str, Any]], front_ips: set[str]) -> list[str]:
    """The other direction: every write an MCP server made to a twin belongs to a tool call
    with write access (the next call to complete after it, since calls are synchronous)."""
    problems: list[str] = []
    calls = [(i, e["data"]) for i, e in enumerate(events) if e.get("type") == "mcp.call"]
    for i, event in enumerate(events):
        data = event.get("data", {})
        if (
            event.get("type") != "http.exchange"
            or data.get("client") not in front_ips
            or data.get("method") not in WRITES
        ):
            continue
        following = next((c for j, c in calls if j > i), None)
        if following is None or following.get("access") not in ("write", "admin"):
            tool = following.get("tool") if following else "no tool call"
            where = f"{data.get('host')}{str(data.get('path', '')).split('?')[0]}"
            problems.append(
                f"{data.get('method')} {where} is not explained by a write tool call ({tool})"
            )
    return problems
