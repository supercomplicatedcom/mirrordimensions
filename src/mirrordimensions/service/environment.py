# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""The environment as a map: agents, the gateway, each system and the model endpoints
(build spec, "Portal", "Environment map requirements").

Nodes and edges come from the manifest's apps and model routes and from the agents' grants,
never hand-placed. The layout is a computed left-to-right layering (agents, gateway, systems
and model endpoints), so the same environment always draws the same way.
"""

from __future__ import annotations

from collections.abc import Callable
from io import StringIO
from typing import Any, Literal, cast

from pydantic import BaseModel, Field

from mirrordimensions.config.agent import Agent
from mirrordimensions.config.loader import load_model
from mirrordimensions.config.manifest import Manifest
from mirrordimensions.errors import MirrorError
from mirrordimensions.project import Project
from mirrordimensions.service import agents as agents_svc
from mirrordimensions.service import changes as changes_svc
from mirrordimensions.service.changes import Change
from mirrordimensions.twins.base import get_twin
from mirrordimensions.world import naming

NodeKind = Literal["agent", "gateway", "system", "model", "device"]


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
    location: str | None = None  # devices: site, floor and room, in words
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
    "device-platform": "Building access",
    "message-broker": "Message broker",
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
    nodes += _devices(manifest, edges)
    return Graph(project=manifest.name, nodes=nodes, edges=edges)


def device_location(manifest: Manifest, at: str) -> str:
    """Where a device is, in words: "Headquarters, floor f2, server-room"."""
    site_id, *rest = at.split("/")
    site = next((s for s in manifest.sites if s.id == site_id), None)
    words = [site.name if site else site_id]
    if rest:
        words.append(f"floor {rest[0]}")
    if len(rest) > 1:
        words.append(rest[1].replace("-", " "))
    return ", ".join(words)


def _devices(manifest: Manifest, edges: list[Edge]) -> list[Node]:
    """Each device, beside the platform it is reached through, with where it is."""
    from mirrordimensions.devices import load_type

    nodes: list[Node] = []
    for row, device in enumerate(manifest.devices):
        kind = load_type(device.type).get("label", device.type)
        zone = "restricted" if device.sensitivity == "restricted" else ""
        nodes.append(
            Node(
                id=f"device:{device.id}",
                kind="device",
                label=device.id.replace("-", " ").capitalize(),
                detail=f"{kind} · {zone}" if zone else str(kind),
                location=device_location(manifest, device.at),
                column=3,
                row=row,
            )
        )
        edges.append(
            Edge(source=f"system:{device.platform}", target=f"device:{device.id}", kind="route")
        )
    return nodes


# -- edits: visibility, grants, and the changes still pending (decision 0021) -----------

VISIBILITIES = ("granted", "denied", "present", "absent")
NONE = "none"


def set_visibility(project: Project, app_id: str, state: str) -> Change:
    """Set a system's visibility in mirror.yaml, for every agent. Between granted, denied
    and present it takes effect at the next run; to or from absent, after a rebuild."""
    from mirrordimensions.service.systems import edit_manifest

    if state not in VISIBILITIES:
        raise MirrorError(
            f"{state!r} is not a visibility.",
            f"A system is {', '.join(VISIBILITIES)}.",
            f"Run: mirror set visibility {app_id} granted",
        )
    manifest = _manifest(project)
    app = _app(manifest, app_id)
    before = str(app.visibility)

    def edit(data: Any) -> None:
        for entry in data["apps"]:
            if entry["id"] == app_id:
                entry["visibility"] = state

    if before != state:
        edit_manifest(project, edit)
    return changes_svc.visibility_change(
        app_id,
        system_label(app.kind, app.product, app.id),
        before,
        state,
        changes_svc.built_visibility(project, app_id),
    )


def _app(manifest: Manifest, app_id: str) -> Any:
    app = next((a for a in manifest.apps if a.id == app_id), None)
    if app is None:
        raise MirrorError(
            f"There is no system {app_id!r}.",
            f"Systems: {', '.join(a.id for a in manifest.apps)}.",
            "Run: mirror system list",
        )
    return app


def grant_vocabulary(manifest: Manifest, app_id: str) -> tuple[str | None, tuple[str, ...]]:
    """The key an agent file's grants use for a system, and the levels it accepts: `repos`
    with read, write or admin; `channels` and `tools` by membership. (None, ()) when the
    system is granted as a whole only."""
    app = _app(manifest, app_id)
    if app.kind == "mcp-server" and app.serves is not None:
        return "tools", ("allowed",)
    twin = get_twin(app.product)
    if twin is None:
        return None, ()
    return twin.grant_key, tuple(twin.grant_levels)


def set_grant(project: Project, agent_name: str, resource: str, grant: str) -> Change:
    """Set one grant in an agent file: `code/billing-service write`, `chat/incidents member`,
    `code/billing-service none` to take it away, `chat none` to take away the whole system.
    It takes effect at the agent's next run."""
    from ruamel.yaml import YAML

    from mirrordimensions.config.loader import read_yaml

    agent, path = agents_svc.load_agent(project, agent_name)
    manifest = _manifest(project)
    app_id, _, name = resource.partition("/")
    name = name.lstrip("#")
    key, vocabulary = grant_vocabulary(manifest, app_id)
    levels: list[str] = list(vocabulary)
    current = dict(agent.grants.get(app_id) or {}) if app_id in agent.grants else None
    if not name:
        if grant not in (NONE, "granted"):
            raise MirrorError(
                f"A whole system is granted or not: {grant!r} is neither.",
                "Grant a system with `granted`, take it away with `none`.",
                f"Run: mirror set grant {agent_name} {app_id} granted",
            )
        before: Any = "granted" if current is not None else None
        after: Any = "granted" if grant == "granted" else None
    else:
        if key is None:
            raise MirrorError(
                f"{app_id} is granted as a whole; it has nothing named {name!r} to grant.",
                "Only repositories, channels and tools are granted one by one.",
                f"Run: mirror set grant {agent_name} {app_id} granted",
            )
        allowed = (*levels, NONE) if len(levels) > 1 else (*levels, "member", NONE)
        if grant not in allowed:
            raise MirrorError(
                f"{grant!r} is not a grant for {app_id}.",
                f"Use one of: {', '.join(dict.fromkeys(allowed))}.",
                f"Run: mirror set grant {agent_name} {resource} {levels[0]}",
            )
        _known(project, manifest, app_id, key, name)
        held: Any = (current or {}).get(key)
        if len(levels) > 1:
            before = cast(dict[str, Any], held).get(name) if isinstance(held, dict) else None
            after = None if grant == NONE else grant
        else:
            before = levels[0] if isinstance(held, list) and name in held else None
            after = None if grant == NONE else levels[0]

    def edit(data: Any) -> None:
        grants = data.setdefault("grants", {})
        if not name:
            if after is None:
                grants.pop(app_id, None)
            elif app_id not in grants:
                grants[app_id] = {}
            return
        system: Any = grants.setdefault(app_id, {})
        if system is None:
            grants[app_id] = system = {}
        if len(levels) > 1:
            by_level: Any = system.setdefault(key, {})
            if after is None:
                by_level.pop(name, None)
            else:
                by_level[name] = after
        else:
            held: Any = system.setdefault(key, [])
            if after is None and name in held:
                held.remove(name)
            elif after is not None and name not in held:
                held.append(name)

    if before != after:
        data, problems = read_yaml(path)
        if problems:
            raise MirrorError(f"{path.name} cannot be read.", problems[0].render(), "")
        edit(data)
        yaml = YAML(typ="rt")
        yaml.preserve_quotes = True
        buffer = StringIO()
        yaml.dump(data, buffer)  # pyright: ignore[reportUnknownMemberType]
        text = buffer.getvalue()
        Agent.model_validate(YAML(typ="safe").load(text))  # pyright: ignore[reportUnknownMemberType]  # refuse to write an invalid file
        path.write_bytes(text.encode("utf-8"))
    return changes_svc.grant_change(agent_name, resource, before, after)


def _known(project: Project, manifest: Manifest, app_id: str, key: str, name: str) -> None:
    """Refuse a grant on a repository, channel or tool the world does not have."""
    known: list[str] = []
    if key in ("repos", "channels"):
        try:
            world = agents_svc._world(project)  # pyright: ignore[reportPrivateUsage]
        except MirrorError:
            return  # not generated yet: nothing to check against
        known = (
            [r.name for r in world.repositories]
            if key == "repos"
            else [c.name for c in world.channels]
        )
        # The usual names are kept as written and translated at each run (decision 0029).
        usual = naming.repos(world) if key == "repos" else naming.channels(world)
        if name.split("/")[-1] in usual:
            return
    elif key == "tools":
        from mirrordimensions.service.sandbox import world_plan

        app = next((a for a in world_plan(project, manifest).apps if a.id == app_id), None)
        known = sorted(app.tools.names) if app is not None and app.tools is not None else []
        if not known:
            return
    if name.split("/")[-1] not in known:
        raise MirrorError(
            f"{app_id} has no {key[:-1]} called {name!r}.",
            f"Known: {', '.join(sorted(known))}.",
            "Check the name with: mirror world show projects",
        )


def pending_changes(project: Project) -> list[Change]:
    """Edits saved to mirror.yaml or agent files that are not yet in effect."""
    agents = {
        name: agents_svc.load_agent(project, name)[0].grants
        for name in agents_svc.agent_files(project)
    }
    return changes_svc.pending_changes(project, _manifest(project), agents)


def _quiet(_text: str) -> None:
    return None


class ApplyResult(BaseModel):
    rebuilt: bool = Field(description="The world was rebuilt from the first affected stage")
    applied: list[Change] = Field(description="In effect now")
    waiting: list[Change] = Field(description="In effect at the next run (grants)")


def apply_changes(project: Project, on_step: Callable[[str], None] | None = None) -> ApplyResult:
    """Put pending changes into effect now: rebuild what a rebuild needs (from the first
    affected stage, as `mirror world create --resume`), and hand a running gateway the
    current rules and visibility. Grants wait for the agent's next run, which issues them."""
    from mirrordimensions.hostos.lock import ProjectLock
    from mirrordimensions.network import sandbox
    from mirrordimensions.service import sandbox as sandbox_svc
    from mirrordimensions.service import world as world_svc
    from mirrordimensions.service.sandbox import _docker, world_plan  # pyright: ignore[reportPrivateUsage]

    say: Callable[[str], None] = on_step or _quiet
    pending = pending_changes(project)
    rebuilt = any(c.applies == "rebuild" for c in pending)
    restart = any(c.applies == "restart" for c in pending)
    manifest = _manifest(project)
    plan = world_plan(project, manifest)
    docker, *_ = _docker()

    def ours() -> bool:
        return (
            docker.is_running(sandbox.GATEWAY_NAME)
            and docker.labels(sandbox.GATEWAY_NAME).get(sandbox.LABEL) == manifest.name
        )

    if rebuilt:
        # The systems are built again from scratch, and seeded again: from stage 1 if the
        # company changed, else from stage 2 (decision 0021).
        stage = 1 if any(c.kind == "company" for c in pending) else 2
        say(f"Rebuilding the world from stage {stage}")
        world_svc.create_world(project, from_stage=stage, on_stage=say)
    elif restart and ours():
        say("Restarting the sandbox: a system leaves or joins the network")
        sandbox_svc.down(project)
        sandbox_svc.up(project, on_step=say)
    if ours():
        with ProjectLock(project.state_dir, "apply"):
            sandbox.refresh_routes(docker, plan)
            changes_svc.record_applied(project, manifest)
        say("The gateway has the current rules and visibility")
    elif not rebuilt:
        say("The sandbox is down: everything saved applies when it next starts")
        changes_svc.record_applied(project, manifest)
    waiting = [c for c in pending if c.kind == "grant"]
    applied = [c for c in pending if c.kind != "grant"]
    return ApplyResult(rebuilt=rebuilt, applied=applied, waiting=waiting)


class GrantItem(BaseModel):
    name: str
    label: str
    grant: str | None = Field(description="The level granted, `member`, `allowed`, or None")


class GrantSystem(BaseModel):
    app_id: str
    label: str
    key: str | None = Field(description="repos, channels or tools; None if granted whole")
    levels: list[str]
    granted: bool = Field(description="The agent file grants this system at all")
    items: list[GrantItem]


def grant_options(project: Project, agent_name: str) -> list[GrantSystem]:
    """Every repository, channel and tool an agent could be granted, system by system,
    with what its file grants now: the Permissions screen's editor."""
    agent, _ = agents_svc.load_agent(project, agent_name)
    manifest = _manifest(project)
    try:
        world = agents_svc._world(project)  # pyright: ignore[reportPrivateUsage]
    except MirrorError:
        world = None
    out: list[GrantSystem] = []
    for app in manifest.apps:
        if app.build == "unavailable":
            continue
        key, levels = grant_vocabulary(manifest, app.id)
        system = agent.grants.get(app.id)
        held: Any = (system or {}).get(key) if key else None
        names: list[str] = []
        if key == "repos" and world is not None:
            names = [r.name for r in world.repositories]
        elif key == "channels" and world is not None:
            names = [c.name for c in world.channels if c.name != "town-square"]
        elif key == "tools":
            from mirrordimensions.service.sandbox import world_plan

            planned = next((a for a in world_plan(project, manifest).apps if a.id == app.id), None)
            names = list(planned.tools.names) if planned and planned.tools else []
        items: list[GrantItem] = []
        for name in names:
            if isinstance(held, dict):
                grant = cast(dict[str, Any], held).get(name)
            elif isinstance(held, list):
                grant = levels[0] if name in cast(list[Any], held) else None
            else:
                grant = None
            label = f"#{name}" if key == "channels" else name
            items.append(GrantItem(name=name, label=label, grant=grant))
        out.append(
            GrantSystem(
                app_id=app.id,
                label=system_label(app.kind, app.product, app.id),
                key=key,
                levels=list(levels),
                granted=app.id in agent.grants,
                items=items,
            )
        )
    return out
