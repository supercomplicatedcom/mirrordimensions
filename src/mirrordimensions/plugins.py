# SPDX-License-Identifier: Apache-2.0
"""Plug-in points, loaded as Python entry points.

Each group has a protocol the plug-in must meet. Engine drivers, run storage, portal
authentication, twin adapters, importers, check functions and event sinks can all be
added by another installed package without changing this one. Discovery reads entry-point
metadata only; nothing is imported until a plug-in is used.
"""

from __future__ import annotations

from importlib.metadata import EntryPoint, entry_points
from typing import Any

from mirrordimensions.config.result import PluginRef

GROUPS: dict[str, str] = {
    "engine": "mirrordimensions.engines",
    "run_store": "mirrordimensions.run_stores",
    "authenticator": "mirrordimensions.authenticators",
    "twin": "mirrordimensions.twins",
    "importer": "mirrordimensions.importers",
    "check": "mirrordimensions.checks",
    "sink": "mirrordimensions.sinks",
}


def _ref(group: str, ep: EntryPoint) -> PluginRef:
    dist = ep.dist
    return PluginRef(
        group=group,
        name=ep.name,
        target=ep.value,
        distribution=dist.name if dist is not None else None,
        version=dist.version if dist is not None else None,
    )


def discover() -> list[PluginRef]:
    """Every registered plug-in, sorted by group and name."""
    refs: list[PluginRef] = []
    for kind, group in GROUPS.items():
        for ep in entry_points(group=group):
            refs.append(_ref(kind, ep))
    return sorted(refs, key=lambda r: (r.group, r.name))


def load(kind: str, name: str) -> Any:
    """Import and return one plug-in's object."""
    group = GROUPS[kind]
    matches = [ep for ep in entry_points(group=group) if ep.name == name]
    if not matches:
        raise KeyError(f"no {kind} plug-in named {name!r}")
    return matches[0].load()
