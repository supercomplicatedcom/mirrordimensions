# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""Onboarding an agent in six steps (build spec, "Onboarding flows").

The same steps run in `mirror agent new` and, later, the portal wizard. Each step writes the
agent file with `status: draft` and the step reached, so onboarding can be left at any point
and resumed from either interface. Step 6 is the preflight check.

| Step | Question | Fields |
| --- | --- | --- |
| 1 Connect | How does it connect? | mode, image, build |
| 2 Model | Where does its model run? | model (a route in mirror.yaml, or none) |
| 3 Identity | Who does it act as? | acts_as |
| 4 Access | What can it reach? | grants (the role's usual access, then edits) |
| 5 Work | How does it notice work? | wake |
| 6 Check | Is it ready? | preflight; the draft becomes a complete agent file |
"""

from __future__ import annotations

from io import StringIO
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel, ValidationError
from ruamel.yaml import YAML

from mirrordimensions.config.agent import Agent
from mirrordimensions.config.loader import load_model
from mirrordimensions.config.manifest import ModelRoute
from mirrordimensions.errors import MirrorError
from mirrordimensions.hostos.files import write_text
from mirrordimensions.project import Project
from mirrordimensions.service.sandbox import _manifest  # pyright: ignore[reportPrivateUsage]
from mirrordimensions.world.model import Person, World

STEPS = ("connect", "model", "identity", "access", "work", "check")
CLOUD = {
    # provider -> (default host, the provider's usual credential variable)
    "anthropic": ("api.anthropic.com", "ANTHROPIC_API_KEY"),
    "openai": ("api.openai.com", "OPENAI_API_KEY"),
}
CODE_KINDS = ("code-hosting",)
CHAT_KINDS = ("team-chat",)
CODE_PRODUCTS = ("gitea",)
CHAT_PRODUCTS = ("mattermost",)


class AgentDraft(BaseModel):
    """Where onboarding stands: the agent file so far and the next step to answer."""

    name: str
    step: int  # the next step to answer, 1-6; 7 when done
    fields: dict[str, Any]
    path: str

    @property
    def done(self) -> bool:
        return self.step > len(STEPS)


def _path(project: Project, name: str) -> Path:
    return project.agents_dir / f"{name}.yaml"


def _dump(fields: dict[str, Any]) -> str:
    order = (
        "name",
        "mode",
        "status",
        "step",
        "acts_as",
        "image",
        "build",
        "model",
        "wake",
        "env",
        "grants",
    )
    ordered = {k: fields[k] for k in order if k in fields and fields[k] is not None}
    ordered.update({k: v for k, v in fields.items() if k not in ordered and v is not None})
    yaml = YAML()
    yaml.default_flow_style = False
    buffer = StringIO()
    yaml.dump(ordered, buffer)  # pyright: ignore[reportUnknownMemberType]
    return buffer.getvalue()


def load_draft(project: Project, name: str) -> AgentDraft | None:
    path = _path(project, name)
    if not path.is_file():
        return None
    data: dict[str, Any] = YAML(typ="safe").load(path.read_text(encoding="utf-8")) or {}  # pyright: ignore[reportUnknownMemberType]
    step = int(data.get("step") or 1) if data.get("status") == "draft" else len(STEPS) + 1
    return AgentDraft(name=name, step=step, fields=data, path=str(path))


def draft_agent(project: Project, name: str, fields: dict[str, Any] | None = None) -> AgentDraft:
    """Start onboarding `name`, or return the draft already started."""
    existing = load_draft(project, name)
    if existing is not None:
        return existing
    Agent.model_validate({"name": name, "mode": "hosted", "status": "draft", "step": 1})
    data = {"name": name, "status": "draft", "step": 1, **(fields or {})}
    write_text(_path(project, name), _dump(data))
    return AgentDraft(name=name, step=1, fields=data, path=str(_path(project, name)))


def update_draft(project: Project, name: str, step: int, fields: dict[str, Any]) -> AgentDraft:
    """Record the answers to one step and move the draft to the next."""
    draft = load_draft(project, name)
    if draft is None:
        raise MirrorError(f"There is no draft for {name!r}.", "", f"Run: mirror agent new {name}")
    if step > draft.step:
        raise MirrorError(
            f"Step {step} comes after step {draft.step}, which is not answered yet.",
            "Onboarding answers the steps in order.",
            f"Run: mirror agent new {name}",
        )
    answer = _check_step(project, step, {**draft.fields, **fields})
    data = {**draft.fields, **answer}
    reached = max(draft.step, step + 1)
    if reached > len(STEPS) - 1:  # steps 1-5 answered: the file is complete
        data.pop("status", None)
        data.pop("step", None)
        try:
            Agent.model_validate(data)
        except ValidationError as exc:
            raise MirrorError(
                "The agent file is not complete.",
                str(exc.errors()[0]["msg"]),
                "Answer the missing step.",
            ) from exc
    else:
        data["status"], data["step"] = "draft", reached
        Agent.model_validate(data)
    write_text(_path(project, name), _dump(data))
    return AgentDraft(name=name, step=reached, fields=data, path=str(_path(project, name)))


def _check_step(project: Project, step: int, data: dict[str, Any]) -> dict[str, Any]:
    """The step's fields, checked against the world."""
    name = STEPS[step - 1]
    if name == "connect":
        mode = data.get("mode")
        if mode == "remote":
            raise MirrorError(
                "Remote agents are not available yet.",
                "An agent on a vendor's platform reaches the world through its MCP ingress (M7.5).",
                "Choose hosted (a container image) or browser.",
            )
        if mode not in ("hosted", "browser"):
            raise MirrorError(
                "Choose how it connects: hosted or browser.",
                "",
                "Pass --mode hosted or --mode browser.",
            )
        if not data.get("image"):
            raise MirrorError(
                "The agent needs a container image.",
                "Hosted agents run their image; browser agents' programs run in one too.",
                "Pass --image <name:tag> (and --build <folder> to build it here).",
            )
        out: dict[str, Any] = {"mode": mode, "image": data["image"]}
        if data.get("build"):
            folder = Path(str(data["build"])).expanduser().resolve()
            if not (folder / "Dockerfile").is_file():
                raise MirrorError(
                    f"No Dockerfile in {folder}.",
                    "",
                    "Pass the folder holding the agent's Dockerfile.",
                )
            out["build"] = folder.as_posix()
        return out
    if name == "model":
        model = data.get("model")
        routes = {m.name for m in _manifest(project).models}
        if model not in (None, "none") and model not in routes:
            raise MirrorError(
                f"There is no model route called {model!r}.",
                f"Routes in mirror.yaml: {', '.join(sorted(routes)) or 'none'}.",
                "Choose cloud or self-hosted to add one, or none.",
            )
        return {"model": None if model in (None, "none") else model}
    if name == "identity":
        acts = cast(dict[str, Any], data.get("acts_as") or {})
        world = _world(project)
        _person(world, acts)  # raises when nobody matches
        return {"acts_as": acts}
    if name == "access":
        grants = cast(dict[str, Any], data.get("grants") or {})
        apps = {a.id for a in _manifest(project).apps}
        unknown = sorted(set(grants) - apps)
        if unknown:
            raise MirrorError(
                f"No system called {', '.join(unknown)} in this world.",
                f"Systems: {', '.join(sorted(apps))}.",
                "Fix the access, then try again.",
            )
        return {"grants": grants}
    if name == "work":
        wake = cast(dict[str, Any], data.get("wake") or {})
        if data.get("mode") == "hosted" and wake.get("type") not in ("command", "poll"):
            raise MirrorError(
                "Say how the agent notices work.",
                "command: run a command when work arrives; poll: start once and let it watch.",
                "Pass --wake command --command '<program> <args>', or --wake poll.",
            )
        if wake.get("type") == "command" and not wake.get("command"):
            raise MirrorError(
                "A command wake needs the command to run.", "", "Pass --command '<program> <args>'."
            )
        return {"wake": wake or {"type": "poll"}}
    return {}


# -- model routes -----------------------------------------------------------------------------


def add_model_route(
    project: Project,
    where: str,
    *,
    provider: str | None = None,
    host: str | None = None,
    upstream: str | None = None,
    credential_env: str | None = None,
    hosted_tools: str = "block",
    name: str | None = None,
) -> str:
    """Add a model route to mirror.yaml (or find the one already there); return its name."""
    from mirrordimensions.service.systems import _edit_manifest  # pyright: ignore[reportPrivateUsage]

    if where == "in-sandbox":
        raise MirrorError(
            "A model inside the sandbox is not available yet.",
            "Running a model in the engine needs a model server image; it is not part of M4.",
            "Choose cloud or self-hosted, or none.",
        )
    if where == "cloud":
        provider = provider or "anthropic"
        if provider not in CLOUD:
            raise MirrorError(
                f"Cloud provider {provider!r} is not supported for onboarding yet.",
                f"Supported: {', '.join(CLOUD)}.",
                "Add other providers to mirror.yaml by hand (models:).",
            )
        default_host, default_env = CLOUD[provider]
        route: dict[str, Any] = {
            "name": name or provider,
            "provider": provider,
            "host": host or default_host,
            "credential": {"from_env": credential_env or default_env},
            "hosted_tools": hosted_tools,
        }
    elif where == "self-hosted":
        if not host or not upstream:
            raise MirrorError(
                "A self-hosted model needs its host name and upstream address.",
                "The host name is what the agent calls; the upstream is the one address:port"
                " the gateway may reach.",
                "Pass --model-host <name> --upstream <address:port>.",
            )
        route = {
            "name": name or "local",
            "provider": "self-hosted",
            "host": host,
            "upstream": upstream,
            "hosted_tools": hosted_tools,
        }
        if credential_env:
            route["credential"] = {"from_env": credential_env}
    else:
        raise MirrorError(
            f"Unknown model location {where!r}.",
            "",
            "Choose cloud, self-hosted, in-sandbox or none.",
        )
    ModelRoute.model_validate(route)
    existing = next((m for m in _manifest(project).models if m.host == route["host"]), None)
    if existing is not None:
        return existing.name

    def edit(data: Any) -> None:
        data.setdefault("models", []).append(route)

    _edit_manifest(project, edit)
    return str(route["name"])


# -- identity and access ------------------------------------------------------------------


def _world(project: Project) -> World:
    path = project.state_dir / "world.json"
    if not path.is_file():
        raise MirrorError(
            "The world has not been built.",
            "Onboarding picks a person and their access from the generated company.",
            "Run: mirror world create",
        )
    return World.model_validate_json(path.read_text(encoding="utf-8"))


def _person(world: World, acts: dict[str, Any]) -> Person:
    from mirrordimensions.config.agent import ActsAs
    from mirrordimensions.service.agents import resolve_person

    probe = Agent(
        name="onboarding", mode="hosted", status="draft", acts_as=ActsAs.model_validate(acts)
    )
    return resolve_person(world, probe)


def person_for(project: Project, role: str | None = None, person: str | None = None) -> Person:
    acts = {"person": person} if person else {"role": role}
    return _person(_world(project), acts)


def role_defaults(project: Project, role: str, person: str | None = None) -> dict[str, Any]:
    """The usual access of someone in this role at the company: their team's repositories
    with write access, other repositories they have worked in read-only, and the channels
    they belong to."""
    world = _world(project)
    who = _person(world, {"person": person} if person else {"role": role})
    manifest = _manifest(project)
    grants: dict[str, Any] = {}
    team_repos = sorted({r for p in world.projects if p.team == who.team for r in p.repositories})
    worked_in = sorted(
        {r.name for r in world.repositories if any(c.author == who.id for c in r.commits)}
        - set(team_repos)
    )
    channels = sorted(c.name for c in world.channels if who.id in c.members and not c.private)
    for app in manifest.apps:
        if app.visibility == "absent" or app.build == "unavailable":
            continue
        if app.kind in CODE_KINDS or app.product in CODE_PRODUCTS:
            repos = {r: "write" for r in team_repos} | {r: "read" for r in worked_in}
            if repos:
                grants[app.id] = {"repos": repos}
        elif (app.kind in CHAT_KINDS or app.product in CHAT_PRODUCTS) and channels:
            grants[app.id] = {"channels": channels}
    return grants


def describe_grants(grants: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for app, grant in grants.items():
        parts: list[str] = []
        repos = cast(dict[str, str], grant.get("repos") or {})
        parts += [f"{repo} ({level})" for repo, level in repos.items()]
        parts += list(grant.get("channels") or [])
        if grant.get("tools") is not None:
            parts.append("tools: " + ", ".join(grant["tools"]))
        lines.append(f"{app}: " + (", ".join(parts) or "all it offers"))
    return lines


def complete_file(project: Project, source: Path) -> Agent:
    """`--file`: a complete agent file, registered as `mirror agent add` does."""
    from mirrordimensions.service.agents import add_agent

    agent, problems = load_model(source, Agent)
    if agent is None:
        raise MirrorError(
            f"{source} is not a valid agent file.",
            problems[0].render() if problems else "",
            "Fix it and try again.",
        )
    return add_agent(project, source)
