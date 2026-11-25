# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""The environment as a map: agents, the gateway, each system and the model endpoints
(build spec, "Portal", "Environment map requirements").

Nodes and edges come from the manifest's apps and model routes and from the agents' grants,
never hand-placed. The layout is a computed left-to-right layering (agents, gateway, systems
and model endpoints), so the same environment always draws the same way.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from mirrordimensions.config.agent import Agent
from mirrordimensions.config.loader import load_model
from mirrordimensions.config.manifest import Manifest
from mirrordimensions.errors import MirrorError
from mirrordimensions.project import Project
from mirrordimensions.service import agents as agents_svc
from mirrordimensions.twins.base import get_twin

NodeKind = Literal["agent", "gateway", "system", "model"]


class Node(BaseModel):
    id: str
    kind: NodeKind
    label: str
    detail: str = ""
    hostname: str | None = None
    product: str | None = None
    visibility: str | None = None  # granted, denied, present, absent (systems only)
    built_as: str | None = None  # real software, stand-in page, unavailable
    granted_to: list[str] = Field(default_factory=list[str])  # agents with grants on it
    column: int
    row: int


class Edge(BaseModel):
    source: str
    target: str
    kind: Literal["route", "grant", "exit"]
    label: str = ""


class Graph(BaseModel):
    project: str
    nodes: list[Node]
    edges: list[Edge]


KIND_LABELS = {
    "code-hosting": "Code hosting",
    "team-chat": "Team chat",
    "mcp-server": "Tools server",
    "wiki": "Wiki",
    "ticketing": "Tickets",
}


def _manifest(project: Project) -> Manifest:
    manifest, problems = load_model(project.manifest_path, Manifest)
    if manifest is None:
        raise MirrorError(
            "mirror.yaml is not valid.",
            problems[0].render() if problems else "",
            "Run: mirror validate",
        )
    return manifest


def system_label(kind: str | None, product: str | None, app_id: str) -> str:
    """A system's name in plain words, by its kind: `Code hosting`, `Team chat`."""
    if kind and kind in KIND_LABELS:
        return KIND_LABELS[kind]
    if kind:
        return kind.replace("-", " ").capitalize()
    return (product or app_id).capitalize()


def environment_graph(project: Project) -> Graph:
    manifest = _manifest(project)
    agents: list[Agent] = []
    for name in sorted(agents_svc.agent_files(project)):
        try:
            agents.append(agents_svc.load_agent(project, name)[0])
        except MirrorError:
            continue  # an invalid agent file is reported by mirror validate, not drawn
    nodes: list[Node] = []
    edges: list[Edge] = []
    for row, agent in enumerate(agents):
        acts = agent.acts_as
        who = (acts.role or acts.person or "someone") if acts else "someone"
        article = "an" if who[:1].lower() in "aeiou" else "a"
        nodes.append(
            Node(
                id=f"agent:{agent.name}",
                kind="agent",
                label=agent.name,
                detail=f"acts as {article} {who}" if acts and acts.role else f"acts as {who}",
                column=0,
                row=row,
            )
        )
        edges.append(Edge(source=f"agent:{agent.name}", target="gateway", kind="route"))
    nodes.append(
        Node(
            id="gateway",
            kind="gateway",
            label="Gateway",
            detail="DNS, TLS, capture",
            column=1,
            row=0,
        )
    )
    row = 0
    for app in manifest.apps:
        twin = get_twin(app.product)
        built_as = (
            "unavailable"
            if app.build == "unavailable"
            else "real software"
            if twin is not None or (app.kind == "mcp-server" and app.serves is not None)
            else "stand-in page"
        )
        granted_to = sorted(a.name for a in agents if app.id in a.grants)
        nodes.append(
            Node(
                id=f"system:{app.id}",
                kind="system",
                label=system_label(app.kind, app.product, app.id),
                detail=(app.product or "").capitalize() if app.product else (app.kind or ""),
                hostname=app.hostname,
                product=app.product,
                visibility=app.visibility,
                built_as=built_as,
                granted_to=granted_to,
                column=2,
                row=row,
            )
        )
        row += 1
        if app.visibility != "absent":
            edges.append(Edge(source="gateway", target=f"system:{app.id}", kind="route"))
        for agent_name in granted_to:
            edges.append(
                Edge(
                    source=f"agent:{agent_name}",
                    target=f"system:{app.id}",
                    kind="grant",
                    label="granted",
                )
            )
    for route in manifest.models:
        nodes.append(
            Node(
                id=f"model:{route.name}",
                kind="model",
                label="Model API",
                detail=f"{route.provider} · outside the sandbox",
                hostname=route.host,
                column=2,
                row=row,
            )
        )
        row += 1
        edges.append(
            Edge(source="gateway", target=f"model:{route.name}", kind="exit", label="only exit")
        )
    return Graph(project=manifest.name, nodes=nodes, edges=edges)
