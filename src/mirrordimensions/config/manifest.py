# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""The environment manifest, `mirror.yaml`: the single source of truth for a world.

The schema is the union of every shape in the build spec: the early manifest, world
definition (industry, tidiness, kind, links, data), systems (settings, data, rules),
physical objects (sites, devices), import (infrastructure) and MCP (serves, remote).
"""

from __future__ import annotations

from typing import Any, Literal, Self

from pydantic import Field, model_validator

from mirrordimensions.config.common import (
    EnvName,
    Hostname,
    Id,
    StrictModel,
    duplicates_ignoring_case,
)

Visibility = Literal["granted", "denied", "present", "absent"]


class Company(StrictModel):
    name: str = Field(min_length=2, max_length=80)
    domain: Hostname
    industry: str = "software"
    size: int = Field(default=25, ge=2, le=100_000, description="Number of people")
    history_days: int = Field(default=180, ge=1, le=3650)
    tidiness: Literal["tidy", "realistic", "messy"] = "realistic"
    seed: int = Field(ge=0, le=2**63 - 1)


class Rule(StrictModel):
    name: Id
    match: dict[str, Any]
    input: dict[str, Any] | None = None
    output: dict[str, Any] | None = None
    when: dict[str, Any] | None = None


class McpServes(StrictModel):
    tools_from: dict[str, Any] = Field(description="file, import, or catalog")
    backed_by: list[Id] = Field(default_factory=list[str])


class McpRemote(StrictModel):
    hostname: Hostname
    auth: Literal["oauth"] = "oauth"


class App(StrictModel):
    id: Id
    kind: str | None = Field(
        default=None, description="World-level kind, e.g. code-hosting, team-chat"
    )
    product: str | None = Field(default=None, description="The product a twin runs, e.g. gitea")
    hostname: Hostname
    visibility: Visibility = "granted"
    build: Literal["unavailable"] | None = None
    settings: dict[str, Any] = Field(default_factory=dict[str, Any])
    data: dict[str, Any] = Field(default_factory=dict[str, Any])
    rules: list[Rule] = Field(default_factory=list[Rule])
    serves: McpServes | None = None
    remote: McpRemote | None = None

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.kind is None and self.product is None:
            raise ValueError("needs a kind, a product, or both")
        if (self.serves or self.remote) and self.kind != "mcp-server":
            raise ValueError("serves and remote are only allowed on kind: mcp-server")
        names = [rule.name for rule in self.rules]
        dupes = duplicates_ignoring_case(names)
        if dupes:
            raise ValueError(f"rule names must be unique: {', '.join(dupes)}")
        return self


class Credential(StrictModel):
    inject: Literal["header"] = "header"
    from_env: EnvName


Provider = Literal[
    "openai", "google-vertex", "azure-openai", "anthropic", "aws-bedrock", "self-hosted"
]


class ModelRoute(StrictModel):
    name: Id
    provider: Provider
    host: Hostname
    credential: Credential | None = None
    hosted_tools: Literal["block", "flag", "allow"] = "block"
    upstream: str | None = Field(
        None,
        pattern=r"^[A-Za-z0-9.\-]+:\d{1,5}$",
        description="self-hosted only: the one address and port this route may reach",
    )

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.provider == "self-hosted" and self.upstream is None:
            raise ValueError("a self-hosted route needs upstream: <address>:<port>")
        if self.provider != "self-hosted" and self.upstream is not None:
            raise ValueError("upstream is only allowed for provider: self-hosted")
        return self


class Isolation(StrictModel):
    runtime: Literal["auto", "gvisor", "default"] = "auto"


class DataScale(StrictModel):
    repositories: int | None = Field(default=None, ge=0)
    issues: int | None = Field(default=None, ge=0)
    messages: int | None = Field(default=None, ge=0)
    canaries: int | None = Field(default=None, ge=0)


class Floor(StrictModel):
    id: Id
    rooms: list[Id] = Field(default_factory=list[str])


class Site(StrictModel):
    id: Id
    name: str
    floors: list[Floor] = Field(default_factory=list[Floor])


class Device(StrictModel):
    id: Id
    type: Id
    at: str = Field(pattern=r"^[a-z0-9-]+(/[a-z0-9-]+){0,2}$", description="site/floor/room")
    platform: Id
    sensitivity: Literal["normal", "restricted"] = "normal"


class Manifest(StrictModel):
    version: Literal[1]
    name: Id
    status: Literal["draft", "defined"] = "defined"
    company: Company
    apps: list[App] = Field(default_factory=list[App])
    links: list[dict[str, dict[str, Any]]] = Field(default_factory=list[dict[str, dict[str, Any]]])
    data: DataScale | None = None
    models: list[ModelRoute] = Field(default_factory=list[ModelRoute])
    isolation: Isolation = Field(default_factory=Isolation)
    sites: list[Site] = Field(default_factory=list[Site])
    devices: list[Device] = Field(default_factory=list[Device])
    infrastructure: list[dict[str, Any]] = Field(default_factory=list[dict[str, Any]])

    @model_validator(mode="after")
    def _unique(self) -> Self:
        for label, values in (
            ("app ids", [a.id for a in self.apps]),
            ("app hostnames", [a.hostname for a in self.apps]),
            ("model route names", [m.name for m in self.models]),
            ("site ids", [s.id for s in self.sites]),
            ("device ids", [d.id for d in self.devices]),
        ):
            dupes = duplicates_ignoring_case(values)
            if dupes:
                raise ValueError(f"{label} must be unique ignoring case: {', '.join(dupes)}")
        app_ids = {a.id for a in self.apps}
        for app in self.apps:
            if app.serves:
                missing = [b for b in app.serves.backed_by if b not in app_ids]
                if missing:
                    raise ValueError(
                        f"app {app.id} is backed by unknown apps: {', '.join(missing)}"
                    )
        for link in self.links:
            if len(link) != 1:
                raise ValueError("each link has exactly one kind, e.g. announce: {...}")
        return self
