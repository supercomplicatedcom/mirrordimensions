# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""Agents: register agent files, issue their identities, and run a hosted agent once
(build spec, "How an agent enters the world" and "Agent modes")."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from mirrordimensions.agents import hosted
from mirrordimensions.config.agent import Agent

__all__ = ["Agent"]
from mirrordimensions.config.loader import load_model
from mirrordimensions.engine.docker_api import Docker
from mirrordimensions.errors import MirrorError
from mirrordimensions.hostos.files import write_text
from mirrordimensions.network import sandbox
from mirrordimensions.network.events import Collector
from mirrordimensions.project import Project
from mirrordimensions.service.sandbox import _docker, _manifest, app_secrets  # pyright: ignore[reportPrivateUsage]
from mirrordimensions.twins.base import Identity, get_twin
from mirrordimensions.twins.relay import Relay
from mirrordimensions.world.model import Person, World

ARCH = {"aarch64": "arm64", "arm64": "arm64", "x86_64": "amd64", "amd64": "amd64"}


class Exchange(BaseModel):
    method: str
    host: str
    path: str
    status: int | None


class HostedOutcome(BaseModel):
    agent: str
    person: str
    host: str
    address: str
    isolation: str  # full, or reduced when the image runs emulated
    reduced_reason: str | None = None
    exit_code: int
    output: str
    exchanges: list[Exchange]


def agent_files(project: Project) -> dict[str, Path]:
    found: dict[str, Path] = {}
    folder = project.agents_dir
    if folder.is_dir():
        for path in sorted([*folder.glob("*.yaml"), *folder.glob("*.yml")]):
            agent, _ = load_model(path, Agent)
            if agent is not None:
                found[agent.name] = path
    return found


def load_agent(project: Project, name: str) -> tuple[Agent, Path]:
    files = agent_files(project)
    if name not in files:
        raise MirrorError(
            f"There is no agent called {name!r}.",
            f"Agents: {', '.join(files) or 'none'}.",
            "Run: mirror agent add <file>",
        )
    agent, problems = load_model(files[name], Agent)
    if agent is None:
        raise MirrorError(
            f"The agent file for {name!r} is not valid.",
            problems[0].render(),
            "Run: mirror validate",
        )
    return agent, files[name]


def add_agent(project: Project, source: Path) -> Agent:
    """Copy an agent file into the project; a build folder is recorded as an absolute path."""
    agent, problems = load_model(source, Agent)
    if agent is None:
        raise MirrorError(
            f"{source} is not a valid agent file.",
            problems[0].render() if problems else "",
            "Fix it and try again.",
        )
    manifest = _manifest(project)
    unknown = sorted(set(agent.grants) - {a.id for a in manifest.apps})
    if unknown:
        raise MirrorError(
            f"The agent is granted access to systems this world does not have: {', '.join(unknown)}.",
            f"Systems: {', '.join(a.id for a in manifest.apps)}.",
            "Fix the grants in the agent file.",
        )
    text = source.read_text(encoding="utf-8")
    if agent.build is not None:
        folder = (source.parent / agent.build).resolve()
        if not (folder / "Dockerfile").is_file():
            raise MirrorError(
                f"No Dockerfile in {folder}.",
                "The agent file's build folder needs one.",
                "Fix build: in the agent file.",
            )
        text = (
            "\n".join(
                f"build: {folder.as_posix()}" if line.startswith("build:") else line
                for line in text.splitlines()
            )
            + "\n"
        )
    write_text(project.agents_dir / f"{agent.name}.yaml", text)
    return agent


def remove_agent(project: Project, name: str) -> None:
    _, path = load_agent(project, name)
    path.unlink()


def _world(project: Project) -> World:
    path = project.state_dir / "world.json"
    if not path.is_file():
        raise MirrorError(
            "The world has not been built.", "There is no world.json.", "Run: mirror world create"
        )
    return World.model_validate_json(path.read_text(encoding="utf-8"))


def resolve_person(world: World, agent: Agent) -> Person:
    """The person the agent acts as: named, or the first current employee with the role."""
    acts = agent.acts_as
    if acts is None:
        raise MirrorError(
            f"The agent {agent.name!r} has no acts_as.",
            "Who it acts as is not set.",
            "Set acts_as in the agent file.",
        )
    current = [p for p in world.people if p.left_ago is None]
    if acts.person is not None:
        match = [p for p in current if acts.person in (p.id, p.username, p.name)]
        if not match:
            raise MirrorError(
                f"No current employee called {acts.person!r}.",
                "acts_as.person names nobody in the world.",
                "Run: mirror world show, then fix acts_as.",
            )
        return match[0]
    with_role = sorted((p for p in current if acts.role in p.roles), key=lambda p: p.id)
    if not with_role:
        raise MirrorError(
            f"Nobody in the company has the role {acts.role!r}.",
            "acts_as.role matches no one.",
            "Choose another role or name a person.",
        )
    return with_role[0]


def _grants(agent: Agent, app: sandbox.App, world: World) -> dict[str, Any]:
    grants = dict(agent.grants.get(app.id, {}))
    grants.setdefault("owner", world.org)  # repositories without an owner are the company's
    grants.setdefault("team", world.org)  # chat channels are the company's team's
    return grants


def issue(
    project: Project, agent: Agent, docker: Docker | None = None
) -> tuple[Person, dict[str, Identity]]:
    """Create or update the person's account in each granted system; credentials in production form."""
    world = _world(project)
    person = resolve_person(world, agent)
    manifest = _manifest(project)
    plan = sandbox.plan_from(manifest)
    docker = docker or _docker()[0]
    secrets = app_secrets(project, manifest)
    relay = Relay(docker)
    identities: dict[str, Identity] = {}
    for app in plan.apps:
        if app.id not in agent.grants:
            continue
        twin = get_twin(app.product)
        if twin is None:
            continue
        ctx = sandbox.twin_context(plan, app, secrets)
        identities[app.id] = twin.issue_identity(
            relay, ctx, person.username, person.name, person.email, _grants(agent, app, world)
        )
    return person, identities


def creds(project: Project, name: str) -> dict[str, Any]:
    agent, _ = load_agent(project, name)
    person, identities = issue(project, agent)
    return {
        "person": f"{person.name} ({person.username}), {person.title}",
        "systems": {
            app: {"username": i.username, "env": sorted(i.env), "token": i.token[:4] + "…"}
            for app, i in identities.items()
        },
    }


def engine_arch(docker: Docker) -> str:
    return ARCH.get(str(docker.info().get("Architecture")), "amd64")


def ensure_image(docker: Docker, agent: Agent) -> str | None:
    """Build the agent's image when it has a build folder; return the architecture it has."""
    assert agent.image is not None  # noqa: S101 (validated: hosted agents have an image)
    if agent.build is not None:
        folder = Path(agent.build)
        context = {
            p.relative_to(folder).as_posix(): p.read_bytes()
            for p in sorted(folder.rglob("*"))
            if p.is_file()
        }
        docker.build(context, agent.image)
    elif docker.image_arch(agent.image) is None:
        try:
            docker.pull(agent.image)
        except Exception as exc:
            raise MirrorError(
                f"Cannot get the agent's image {agent.image}.",
                str(exc)[:200],
                "Check the image name, or log in to its registry on the engine.",
            ) from exc
    return ARCH.get(docker.image_arch(agent.image) or "", docker.image_arch(agent.image))


def run_hosted(
    project: Project, name: str, allow_emulated: bool = False, timeout_s: int = 300
) -> HostedOutcome:
    """Issue the agent's identity, start its container as deployed, let it finish, and
    return what the gateway saw it do."""
    agent, _ = load_agent(project, name)
    if agent.mode != "hosted":
        raise MirrorError(
            f"{name} is a {agent.mode} agent.",
            "Only hosted agents run in a container of their own.",
            "Use the browser runner for browser agents.",
        )
    manifest = _manifest(project)
    plan = sandbox.plan_from(manifest)
    docker, _, _, offset = _docker()
    for needed in (sandbox.DNS_NAME, sandbox.GATEWAY_NAME):
        if not docker.is_running(needed):
            raise MirrorError(
                "The world is not running.", f"{needed} is not running.", "Run: mirror up"
            )
    arch = ensure_image(docker, agent)
    native = engine_arch(docker)
    platform, reduced = None, None
    if arch != native:
        if not allow_emulated:
            raise MirrorError(
                f"The agent's image is {arch}, and the engine runs {native}.",
                "Emulated agents run at reduced isolation.",
                f"Build the image for {native}, or pass --allow-emulated to run it at reduced isolation.",
            )
        platform, reduced = f"linux/{arch}", f"image is {arch}, emulated on {native}"
    person, identities = issue(project, agent, docker)
    where = hosted.placement(plan, agent.name)
    # The agent's own variables win; model keys default to placeholders the gateway replaces.
    env = {**hosted.model_placeholders(plan), **hosted.environment(agent.env, identities)}
    bridges = {
        f"br-{docker.network_id(n)[:12]}": n for n in (sandbox.LAN, sandbox.APPS, sandbox.UPLINK)
    }
    collector = Collector(docker, project.state_dir / "sandbox" / "events.jsonl", bridges, offset)
    collector.start()
    ca_pem = (project.state_dir / "ca" / "root-ca.crt").read_bytes()
    command = agent.wake.command if agent.wake and agent.wake.type == "command" else None
    container = hosted.spec(plan, where, agent.image or "", env, platform)
    if command:
        container.command = command
    started = time.time()
    try:
        hosted.start(docker, container, ca_pem)
        result = docker.wait(where.name, timeout_s=timeout_s)
        time.sleep(1.5)  # the last exchanges reach the collector within a second
        exchanges = [
            Exchange(
                method=e["data"]["method"],
                host=e["data"]["host"],
                path=e["data"]["path"].split("?")[0],
                status=e["data"].get("status"),
            )
            for e in collector.events
            if e.get("type") == "http.exchange"
            and e["data"].get("client") == where.ip
            and e["arrived"] - offset >= started
        ]
    finally:
        docker.remove(where.name)
    return HostedOutcome(
        agent=agent.name,
        person=person.username,
        host=where.name,
        address=where.ip,
        isolation="reduced" if reduced else "full",
        reduced_reason=reduced,
        exit_code=result.exit_code,
        output=result.output[-2000:],
        exchanges=exchanges,
    )


class PreflightCheck(BaseModel):
    name: str
    outcome: str  # pass, fail, n/a
    detail: str = ""
    fix: str = ""


def check_agent(project: Project, name: str, allow_emulated: bool = False) -> list[PreflightCheck]:
    """Preflight without starting a scenario (build spec, "Onboarding flows"). Each failure
    names its fix; the agent is ready only when none fails."""
    from mirrordimensions.world.denylist import findings

    checks: list[PreflightCheck] = []

    def add(check: str, ok: bool | None, detail: str = "", fix: str = "") -> bool:
        outcome = "n/a" if ok is None else ("pass" if ok else "fail")
        checks.append(
            PreflightCheck(
                name=check, outcome=outcome, detail=detail, fix="" if ok or ok is None else fix
            )
        )
        return bool(ok)

    try:
        agent, _ = load_agent(project, name)
    except MirrorError as exc:
        add("The agent file is valid", False, exc.what, exc.fix)
        return checks
    if not add(
        "The agent file is complete",
        agent.status != "draft",
        f"step {agent.step} of 6" if agent.status else "",
        f"Run: mirror agent new --resume {name}",
    ):
        return checks
    if agent.mode != "hosted":
        add(f"{agent.mode.capitalize()} agents", None, "checked in a later milestone")
        return checks
    manifest = _manifest(project)
    plan = sandbox.plan_from(manifest)
    docker, _, _, _ = _docker()
    if not add(
        "The world is running",
        all(docker.is_running(n) for n in (sandbox.DNS_NAME, sandbox.GATEWAY_NAME)),
        fix="Run: mirror up",
    ):
        return checks
    try:
        arch = ensure_image(docker, agent)
    except MirrorError as exc:
        add("The image exists", False, exc.what, exc.fix)
        return checks
    native = engine_arch(docker)
    if arch == native:
        add("The image is built for the engine", True, f"{agent.image}, {arch}")
    elif allow_emulated:
        add(
            "The image is built for the engine",
            True,
            f"{arch} on a {native} engine: runs emulated, at reduced isolation",
        )
    else:
        add(
            "The image is built for the engine",
            False,
            f"{agent.image} is {arch}; the engine runs {native}",
            f"Build the image for {native} (docker buildx --platform linux/{native}), or pass --allow-emulated to run it at reduced isolation.",
        )
        return checks
    try:
        person, identities = issue(project, agent, docker)
    except MirrorError as exc:
        add("Identities and credentials are issued", False, exc.what, exc.fix)
        return checks
    add(
        "Identities and credentials are issued",
        True,
        f"as {person.username} in {', '.join(sorted(identities)) or 'no system'}",
    )
    hosts = {a.id: a.hostname for a in plan.apps}
    granted = [hosts[app] for app in agent.grants if app in hosts]
    unresolved = [h for h in granted if h not in plan.resolvable]
    add(
        "Production hostnames resolve to the world",
        not unresolved,
        ", ".join(granted),
        "Make those systems visible in mirror.yaml (visibility: granted).",
    )
    where = hosted.placement(plan, agent.name)
    try:
        env = hosted.environment(agent.env, identities)
    except MirrorError as exc:
        add("The agent's variables are filled", False, exc.what, exc.fix)
        return checks
    container = hosted.spec(
        plan, where, agent.image or "", env, None if arch == native else f"linux/{arch}"
    )
    try:
        docker.create(container)
        bundle = hosted.trust_root(
            docker, where.name, (project.state_dir / "ca" / "root-ca.crt").read_bytes()
        )
        add(
            "The image starts in the sandbox with the company's root trusted",
            True,
            f"root added to {bundle}",
        )
    except MirrorError as exc:
        add(
            "The image starts in the sandbox with the company's root trusted",
            False,
            exc.what,
            exc.fix,
        )
    finally:
        docker.remove(where.name)
    injected = " ".join(
        [
            where.name,
            hosted.CA_FILE,
            *[
                f"{k}={v}"
                for k, i in identities.items()
                for k, v in i.env.items()
                if not k.endswith("TOKEN")
            ],
        ]
    )
    tells = findings(injected)
    add(
        "Nothing the mirror gives the agent names a test",
        not tells,
        ", ".join(tells) or "host name, variables and certificate paths are ordinary",
        "Report this as a bug: an injected name contains a forbidden word.",
    )
    refers_operator = [k for k, v in agent.env.items() if "127.0.0.1" in v or "localhost" in v]
    add(
        "The agent does not reference the operator's tools",
        not refers_operator,
        ", ".join(refers_operator) or "no host-local addresses",
        "Remove references to the host from the agent's variables.",
    )
    add(
        "The model is reachable through its route",
        None,
        "no models in mirror.yaml yet"
        if not plan.model_hosts
        else "model routes arrive later in M4",
    )
    add(
        "Coverage channels report captured",
        True,
        "http and WebSocket at the gateway, DNS at the resolvers, refused connections at the engine",
    )
    return checks
