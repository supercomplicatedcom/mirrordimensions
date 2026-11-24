# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""The access map: hosts, repositories, channels and tools the agent touched, against those
it was granted (build spec, "Timeline and report").

Touched comes from the run's own record: the gateway's exchanges and refused names for
hosts, and the touch ledger for everything inside a system. Granted comes from the agent's
grants. Every row says both, so "used something it was not given" and "was given more than
it needed" read off the same table.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, cast

_REPO = re.compile(r"^(?:repo|file|issue|pull|branch|commit|tag|release|wiki):([^/#\s]+/[^/#\s]+)")


@dataclass(frozen=True)
class Grant:
    """What one system grants the agent: repositories by level, channels, or tools."""

    system: str
    host: str
    owner: str = ""
    repos: dict[str, str] | None = None
    channels: list[str] | None = None
    tools: list[str] | None = None

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"system": self.system, "host": self.host}
        if self.owner:
            out["owner"] = self.owner
        for key in ("repos", "channels", "tools"):
            value = getattr(self, key)
            if value is not None:
                out[key] = value
        return out


def grants_from(raw: list[dict[str, Any]]) -> list[Grant]:
    return [
        Grant(
            system=str(g.get("system", "")),
            host=str(g.get("host", "")),
            owner=str(g.get("owner", "")),
            repos=cast(dict[str, str] | None, g.get("repos")),
            channels=cast(list[str] | None, g.get("channels")),
            tools=cast(list[str] | None, g.get("tools")),
        )
        for g in raw
    ]


def _full(grant: Grant, repo: str) -> str:
    """A granted repository's full name: grants may name it without its owner."""
    return repo if "/" in repo or not grant.owner else f"{grant.owner}/{repo}"


def _repo_level(grants: list[Grant], repo: str) -> str | None:
    for g in grants:
        for granted, level in (g.repos or {}).items():
            if _full(g, granted).lower() == repo.lower():
                return level
    return None


def access_map(
    events: list[dict[str, Any]],
    clients: set[str],
    rows: list[dict[str, Any]],
    grants: list[Grant],
    model_hosts: set[str],
) -> dict[str, Any]:
    """Rows for hosts, repositories, channels and tools, each with `touched` and `granted`."""
    granted_hosts = {g.host.lower() for g in grants} | {h.lower() for h in model_hosts}
    hosts: dict[str, dict[str, Any]] = {}
    for e in events:
        data: dict[str, Any] = e.get("data") or {}
        if data.get("client") not in clients:
            continue
        if e.get("type") in ("http.exchange", "ws.frame"):
            host = str(data.get("host") or "").split(":")[0].lower()
            how = "requests"
        elif e.get("type") == "route.unknown_host":
            host = str(data.get("sni") or data.get("host") or "").lower()
            how = "refused"
        else:
            continue
        if not host:
            continue
        row = hosts.setdefault(
            host, {"host": host, "granted": host in granted_hosts, "requests": 0, "refused": 0}
        )
        row[how] += 1
        row.setdefault("first", e.get("seq"))
    for host in sorted(granted_hosts - set(hosts)):
        hosts[host] = {"host": host, "granted": True, "requests": 0, "refused": 0}

    repos: dict[str, dict[str, Any]] = {}
    channels: dict[str, dict[str, Any]] = {}
    tools: dict[str, dict[str, Any]] = {}
    for r in rows:
        resource = str(r.get("resource", ""))
        how = cast(list[str], r.get("how") or [])
        events_of = cast(list[int], r.get("events") or [])
        if (m := _REPO.match(resource)) is not None:
            target = repos.setdefault(
                m.group(1),
                {"repo": m.group(1), "granted": _repo_level(grants, m.group(1)), "how": []},
            )
        elif resource.startswith("channel:"):
            name = resource.split(":", 1)[1]
            granted = any(name in (g.channels or []) for g in grants)
            target = channels.setdefault(name, {"channel": name, "granted": granted, "how": []})
        elif resource.startswith("tool:"):
            name = resource.split(":", 1)[1]
            granted = any(g.tools is not None and (not g.tools or name in g.tools) for g in grants)
            target = tools.setdefault(name, {"tool": name, "granted": granted, "how": []})
        else:
            continue
        target["how"] = sorted(set(target["how"]) | set(how))
        target.setdefault("first", events_of[0] if events_of else None)
    for g in grants:
        for name, level in (g.repos or {}).items():
            full = _full(g, name)
            if not any(k.lower() == full.lower() for k in repos):
                repos[full] = {"repo": full, "granted": level, "how": []}
        for name in g.channels or []:
            channels.setdefault(name, {"channel": name, "granted": True, "how": []})
        for name in g.tools or []:
            tools.setdefault(name, {"tool": name, "granted": True, "how": []})

    def ordered(rows_by: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        return [rows_by[k] for k in sorted(rows_by)]

    def ungranted(row: dict[str, Any]) -> bool:
        used = bool(row.get("how")) or row.get("requests", 0) or row.get("refused", 0)
        return bool(used) and not row.get("granted")

    tables = {
        "hosts": ordered(hosts),
        "repositories": ordered(repos),
        "channels": ordered(channels),
        "tools": ordered(tools),
    }
    out: dict[str, Any] = dict(tables)
    out["outside_grants"] = sum(ungranted(r) for rows_of in tables.values() for r in rows_of)
    out["grants"] = [g.as_dict() for g in grants]
    return out
