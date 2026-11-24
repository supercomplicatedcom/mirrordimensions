# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""Load a world MCP server's tools and their surfaces, and render the front's configuration.

Two files, both kept in the project:

- **The exported tool list** (`serves.tools_from.file`): what the company's production server
  reports, unchanged. JSON:
  `{"serverInfo": {"name", "version"}, "protocolVersions": [...], "instructions": "...",
  "tools": [ <tools/list entries, verbatim> ]}`.
- **The surfaces** (`serves.surfaces`): for each tool, the twin operations it calls, the
  resource it touches, read or write, and a sentence for the live view. YAML:

      endpoint: /mcp
      backends: {code: {auth: token}, chat: {auth: Bearer}}
      tools:
        list_assigned_issues:
          access: read
          sentence: Lists the issues assigned to it
          steps:
            - {app: code, method: GET, path: /api/v1/repos/issues/search,
               query: {assigned: "true", state: "{state|open}"}}

  In a step, `{name}` is a tool argument, `{name|default}` one with a default, `{$0.id}` a
  field of an earlier step's result, and `{$person}` the caller's username. A body value that
  is exactly one reference keeps the argument's type.

Nothing is fetched from a real server (decision 0009).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from ruamel.yaml import YAML

from mirrordimensions.errors import MirrorError

MODERN = "2026-07-28"
LEGACY = ("2025-11-25", "2025-06-18", "2025-03-26")
KNOWN_VERSIONS = (MODERN, *LEGACY)
AUTH_SCHEMES = ("token", "Bearer")
_REF = re.compile(r"\{([^{}]+)\}")


@dataclass
class Toolset:
    server: dict[str, str]
    versions: list[str]
    instructions: str
    tools: list[dict[str, Any]]  # verbatim from the export
    endpoint: str
    backends: dict[str, dict[str, str]]  # app id -> {auth}
    surfaces: dict[str, dict[str, Any]]  # tool name -> {access, sentence, resource, steps}
    problems: list[str] = field(default_factory=list[str])

    @property
    def names(self) -> list[str]:
        return [str(t["name"]) for t in self.tools]


def _problem(app_id: str, what: str, fix: str) -> MirrorError:
    return MirrorError(f"The MCP server {app_id!r} is not valid: {what}", "", fix)


def load(root: Path, app_id: str, serves: dict[str, Any], app_ids: set[str]) -> Toolset:
    source = cast(dict[str, Any], serves.get("tools_from") or {})
    if "file" not in source:
        kind = next(iter(source), "nothing")
        raise _problem(
            app_id,
            f"tools_from: {kind} is not available yet",
            "Give the exported tool list as tools_from: {file: <path>}. Import arrives in M8.",
        )
    tools_path = root / str(source["file"])
    surfaces_ref = serves.get("surfaces")
    if not surfaces_ref:
        raise _problem(
            app_id,
            "no surfaces file",
            "Add serves.surfaces: <path> mapping each tool to the twin operations it calls.",
        )
    surfaces_path = root / str(surfaces_ref)
    for path in (tools_path, surfaces_path):
        if not path.is_file():
            raise _problem(app_id, f"{path} does not exist", "Fix the path in mirror.yaml.")
    try:
        export = cast(dict[str, Any], json.loads(tools_path.read_text(encoding="utf-8")))
    except ValueError as exc:
        raise _problem(app_id, f"{tools_path.name} is not JSON ({exc})", "Fix the file.") from exc
    mapping = cast(
        dict[str, Any],
        YAML(typ="safe").load(surfaces_path.read_text(encoding="utf-8")) or {},  # pyright: ignore[reportUnknownMemberType]
    )
    toolset = Toolset(
        server={
            "name": str(export.get("serverInfo", {}).get("name", "")),
            "version": str(export.get("serverInfo", {}).get("version", "")),
        },
        versions=[str(v) for v in export.get("protocolVersions", [MODERN, LEGACY[0]])],
        instructions=str(export.get("instructions", "")),
        tools=list(export.get("tools", [])),
        endpoint=str(mapping.get("endpoint", "/mcp")),
        backends={
            k: {"auth": str(v.get("auth", "Bearer"))}
            for k, v in mapping.get("backends", {}).items()
        },
        surfaces=dict(mapping.get("tools", {})),
    )
    problems = validate(toolset, app_ids)
    if problems:
        raise _problem(app_id, problems[0], "Fix the tool list or the surfaces file.")
    return toolset


def validate(toolset: Toolset, app_ids: set[str]) -> list[str]:
    problems: list[str] = []
    if not toolset.server["name"] or not toolset.server["version"]:
        problems.append("serverInfo needs a name and a version, as the production server reports")
    unknown = [v for v in toolset.versions if v not in KNOWN_VERSIONS]
    if unknown or not toolset.versions:
        problems.append(f"protocolVersions must be among {', '.join(KNOWN_VERSIONS)}")
    names = toolset.names
    if len(set(names)) != len(names):
        problems.append("tool names must be unique")
    for app, backend in toolset.backends.items():
        if app not in app_ids:
            problems.append(f"backend {app!r} is not a system in mirror.yaml")
        if backend["auth"] not in AUTH_SCHEMES:
            problems.append(f"backend {app!r}: auth must be one of {', '.join(AUTH_SCHEMES)}")
    for name in names:
        surface = toolset.surfaces.get(name)
        if surface is None:
            problems.append(f"tool {name!r} has no surface: every tool must say what it calls")
            continue
        if surface.get("access") not in ("read", "write", "admin"):
            problems.append(f"tool {name!r}: access must be read, write or admin")
        steps = cast(list[dict[str, Any]], surface.get("steps") or [])
        if not steps:
            problems.append(f"tool {name!r} calls nothing")
        for i, step in enumerate(steps):
            if step.get("app") not in toolset.backends:
                problems.append(f"tool {name!r} step {i}: app must be one of the backends")
            if str(step.get("method", "")).upper() not in ("GET", "POST", "PUT", "PATCH", "DELETE"):
                problems.append(f"tool {name!r} step {i}: unknown method")
            for ref in _REF.findall(json.dumps(step)):
                earlier = re.match(r"\$(\d+)\.", ref)
                if earlier and int(earlier.group(1)) >= i:
                    problems.append(f"tool {name!r} step {i}: {{{ref}}} refers to a later step")
    for extra in sorted(set(toolset.surfaces) - set(names)):
        problems.append(f"surface {extra!r} is not a tool in the exported list")
    return problems


def front_config(
    toolset: Toolset, hosts: dict[str, str], tokens: dict[str, dict[str, Any]] | None = None
) -> dict[str, Any]:
    """The front's whole configuration: tool definitions and routes to twins, nothing else."""
    return {
        "endpoint": toolset.endpoint,
        "server": toolset.server,
        "versions": toolset.versions,
        "instructions": toolset.instructions,
        "tools": toolset.tools,
        "routes": {name: toolset.surfaces[name]["steps"] for name in toolset.names},
        "backends": {
            app: {"base": f"https://{hosts[app]}", "auth": backend["auth"]}
            for app, backend in toolset.backends.items()
            if app in hosts
        },
        "tokens": tokens or {},
    }


def gateway_surfaces(toolset: Toolset) -> dict[str, dict[str, Any]]:
    """What the gateway needs to turn a tool call into an `mcp.call` event."""
    return {
        name: {
            "access": toolset.surfaces[name].get("access"),
            "sentence": toolset.surfaces[name].get("sentence", ""),
            "resource": toolset.surfaces[name].get("resource"),
        }
        for name in toolset.names
    }
