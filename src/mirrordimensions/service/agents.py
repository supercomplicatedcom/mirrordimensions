# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""Agents: register agent files, issue their identities, and run a hosted agent once
(build spec, "How an agent enters the world" and "Agent modes")."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from mirrordimensions.agents import browser, hosted
from mirrordimensions.config.agent import Agent

__all__ = ["Agent"]
from mirrordimensions.config.loader import load_model
from mirrordimensions.engine.docker_api import Docker
from mirrordimensions.errors import MirrorError
from mirrordimensions.hostos.files import write_text
from mirrordimensions.network import sandbox
from mirrordimensions.network.events import Collector, browser_parser
from mirrordimensions.project import Project
from mirrordimensions.service.sandbox import (
    _docker,  # pyright: ignore[reportPrivateUsage]
    _manifest,  # pyright: ignore[reportPrivateUsage]
    app_secrets,
)
from mirrordimensions.service.sandbox import world_plan as project_plan
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
    browser_host: str | None = None  # browser agents: the managed browser's host name
    browser_events: list[dict[str, Any]] = []
    screenshots: str | None = None  # folder holding the observer's screenshots


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


class AgentSummary(BaseModel):
    name: str
    mode: str
    acts_as: str
    state: str
    image: str | None = None
    systems: list[str] = Field(default_factory=list[str])
    last_run: str | None = None
    last_scenario: str | None = None
    last_status: str | None = None


def list_agents(project: Project) -> list[AgentSummary]:
    """The project's agents, each with the person it acts as and its latest run."""
    from mirrordimensions.service import runlog

    latest: dict[str, runlog.RunSummary] = {}
    for r in runlog.list_runs(project):  # newest first
        if r.agent and r.agent not in latest:
            latest[r.agent] = r
    rows: list[AgentSummary] = []
    for name, path in agent_files(project).items():
        agent, _ = load_model(path, Agent)
        if agent is None:
            continue
        who = str(agent.acts_as.person or agent.acts_as.role) if agent.acts_as else "nobody yet"
        last = latest.get(name)
        rows.append(
            AgentSummary(
                name=name,
                mode=agent.mode,
                acts_as=who,
                state=f"draft, step {agent.step} of 6" if agent.status == "draft" else "defined",
                image=agent.image,
                systems=sorted(agent.grants),
                last_run=last.run_id if last else None,
                last_scenario=last.scenario if last else None,
                last_status=last.status if last else None,
            )
        )
    return rows


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
    plan = project_plan(project, manifest)
    docker = docker or _docker()[0]
    secrets = app_secrets(project, manifest)
    relay = Relay(docker)
    identities: dict[str, Identity] = {}
    for app in plan.apps:
        # Absent: not in the mirror. Present: running, but not in the agent's tools, so it
        # gets no credentials there (build spec, visibility states).
        if app.id not in agent.grants or app.visibility in ("absent", "present"):
            continue
        twin = get_twin(app.product)
        if twin is None:
            continue
        ctx = sandbox.twin_context(plan, app, secrets)
        identities[app.id] = twin.issue_identity(
            relay, ctx, person.username, person.name, person.email, _grants(agent, app, world)
        )
    for app in plan.apps:
        if app.is_mcp and app.tools is not None and app.id in agent.grants:
            identities[app.id] = _issue_mcp(docker, plan, app, agent, person, identities, secrets)
    return person, identities


def _issue_mcp(
    docker: Docker,
    plan: sandbox.Plan,
    app: sandbox.App,
    agent: Agent,
    person: Person,
    identities: dict[str, Identity],
    secrets: dict[str, str],
) -> Identity:
    """A bearer token for the world MCP server, in the form its production server issues.
    The server acts as the person in each backing system, with the person's own credentials
    there, so out-of-grant calls fail as they would in production."""
    assert app.tools is not None  # noqa: S101 (checked by the caller)
    key = secrets.get(f"{app.id}:secret_key", "").encode()
    token = hmac.new(key, person.username.encode(), hashlib.sha256).hexdigest()[:40]
    tools = agent.grants[app.id].get("tools")
    entry: dict[str, object] = {
        "person": person.username,
        "backends": {b: identities[b].token for b in app.tools.backends if b in identities},
        "tools": list(tools) if tools is not None else None,
    }
    current = docker.read_file(app.container, sandbox.MCP_CONFIG)
    config: dict[str, Any] = json.loads(current) if current else {}
    if not config:
        raise MirrorError(
            f"The MCP server {app.id} is not running.",
            f"{app.container} has no configuration.",
            "Run: mirror up",
        )
    tokens: dict[str, dict[str, Any]] = config.get("tokens", {})
    config["tokens"] = {t: e for t, e in tokens.items() if e.get("person") != person.username}
    config["tokens"][token] = entry
    docker.put_files(app.container, {sandbox.MCP_CONFIG: (json.dumps(config).encode(), 0o644)})
    prefix = app.id.upper().replace("-", "_")
    return Identity(
        username=person.username,
        password="",
        token=token,
        env={
            f"{prefix}_MCP_URL": f"https://{app.hostname}{app.tools.endpoint}",
            f"{prefix}_MCP_TOKEN": token,
        },
    )


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


@dataclass
class AgentHandle:
    """A started agent: its workstation, and its managed browser for browser agents."""

    agent: Agent
    where: hosted.Placement
    desk: browser.BrowserPlacement | None
    shots: Path

    @property
    def clients(self) -> set[str]:
        """Addresses whose traffic is the agent's."""
        return {self.where.ip} | ({self.desk.ip} if self.desk else set[str]())


def image_platform(
    docker: Docker, agent: Agent, allow_emulated: bool
) -> tuple[str | None, str | None]:
    """(platform to run, reason it is reduced) for the agent's image; builds it if needed."""
    arch = ensure_image(docker, agent)
    native = engine_arch(docker)
    if arch == native:
        return None, None
    if not allow_emulated:
        raise MirrorError(
            f"The agent's image is {arch}, and the engine runs {native}.",
            "Emulated agents run at reduced isolation.",
            f"Build the image for {native}, or pass --allow-emulated to run it at reduced isolation.",
        )
    return f"linux/{arch}", f"image is {arch}, emulated on {native}"


def start_agent(
    project: Project,
    docker: Docker,
    plan: sandbox.Plan,
    agent: Agent,
    identities: dict[str, Identity],
    collector: Collector,
    platform: str | None,
    shots: Path,
    before_start: Callable[[str], None] | None = None,
) -> AgentHandle:
    """Start the agent as deployed: the managed browser first for browser agents, then the
    agent's own container with its variables and the company root trusted."""
    where = hosted.placement(plan, agent.name)
    ca_pem = (project.state_dir / "ca" / "root-ca.crt").read_bytes()
    desk = browser.placement(plan, agent.name) if agent.mode == "browser" else None
    if desk is None:
        # The agent's own variables win; model keys default to placeholders the gateway replaces.
        env = {**hosted.model_placeholders(plan), **hosted.environment(agent.env, identities)}
    else:
        env = {
            **hosted.model_placeholders(plan),
            **browser.environment(agent.env, identities, desk),
        }
    command = agent.wake.command if agent.wake and agent.wake.type == "command" else None
    container = hosted.spec(plan, where, agent.image or "", env, platform)
    if command:
        container.command = command
    handle = AgentHandle(agent=agent, where=where, desk=desk, shots=shots)
    if desk is not None:
        _start_browser(docker, collector, plan, desk, ca_pem, identities, shots, time.time())
    try:
        hosted.start(docker, container, ca_pem, before_start)
    except MirrorError:
        stop_agent(docker, handle)
        raise
    return handle


def stop_agent(docker: Docker, handle: AgentHandle) -> None:
    docker.remove(handle.where.name)
    if handle.desk is not None:
        browser.stop(docker, handle.desk)


def run_hosted(
    project: Project, name: str, allow_emulated: bool = False, timeout_s: int = 300
) -> HostedOutcome:
    """Run a hosted or browser agent once, outside any scenario: issue its identity, start it
    as deployed, let it finish, and return what was captured."""
    agent, _ = load_agent(project, name)
    if agent.mode not in ("hosted", "browser"):
        raise MirrorError(
            f"{name} is a {agent.mode} agent.",
            "Remote agents run on their vendor's platform and reach the world through its MCP ingress.",
            "Remote agents arrive in M7.5.",
        )
    manifest = _manifest(project)
    plan = project_plan(project, manifest)
    docker, _, _, offset = _docker()
    for needed in (sandbox.DNS_NAME, sandbox.GATEWAY_NAME):
        if not docker.is_running(needed):
            raise MirrorError(
                "The world is not running.", f"{needed} is not running.", "Run: mirror up"
            )
    platform, reduced = image_platform(docker, agent, allow_emulated)
    person, identities = issue(project, agent, docker)
    bridges = {
        f"br-{docker.network_id(n)[:12]}": n for n in (sandbox.LAN, sandbox.APPS, sandbox.UPLINK)
    }
    collector = Collector(docker, project.state_dir / "sandbox" / "events.jsonl", bridges, offset)
    collector.start()
    shots = project.state_dir / "sandbox" / "browser" / agent.name
    started = time.time()
    handle = start_agent(project, docker, plan, agent, identities, collector, platform, shots)
    try:
        result = docker.wait(handle.where.name, timeout_s=timeout_s)
        time.sleep(2.5)  # the last exchanges and screenshots reach the collector
        exchanges = [
            Exchange(
                method=e["data"]["method"],
                host=e["data"]["host"],
                path=e["data"]["path"].split("?")[0],
                status=e["data"].get("status"),
            )
            for e in collector.events
            if e.get("type") == "http.exchange"
            and e["data"].get("client") in handle.clients
            and e["arrived"] - offset >= started
        ]
        browser_events = [
            {"type": e["type"], **e["data"]}
            for e in collector.events
            if e.get("source") == "browser" and e["arrived"] - offset >= started
        ]
    finally:
        stop_agent(docker, handle)
    return HostedOutcome(
        agent=agent.name,
        person=person.username,
        host=handle.where.name,
        address=handle.where.ip,
        isolation="reduced" if reduced else "full",
        reduced_reason=reduced,
        exit_code=result.exit_code,
        output=result.output[-2000:],
        exchanges=exchanges,
        browser_host=handle.desk.name if handle.desk else None,
        browser_events=browser_events,
        screenshots=str(shots) if handle.desk else None,
    )


def _start_browser(
    docker: Docker,
    collector: Collector,
    plan: sandbox.Plan,
    desk: browser.BrowserPlacement,
    ca_pem: bytes,
    identities: dict[str, Identity],
    shots: Path,
    after: float,
) -> None:
    """Start the managed browser and its observer, and wait until the observer is ready."""
    image = browser.ensure_image(docker, ca_pem)
    secrets = [s for i in identities.values() for s in (i.password, i.token)]
    secrets += [m.credential for m in plan.models if m.credential]
    browser.start(docker, plan, desk, image, secrets)
    collector.add_source(desk.observer, browser_parser(shots))
    ready = collector.wait_for(
        lambda e: e.get("type") == "browser.observer_ready", after=after - 1, timeout=30
    )
    if ready is None:
        browser.stop(docker, desk)
        raise MirrorError(
            "The managed browser did not start.",
            "Its observer reported nothing within 30 seconds.",
            "Run: mirror agent check <name>, which names the failing step.",
        )


def _model_checks(add: Any, docker: Docker, plan: sandbox.Plan, agent: Agent) -> None:
    """From the agent's network, through the gateway: each model route answers, with the
    real credential added outside. The probe sends an empty request, which providers reject
    before any model runs, so it costs nothing."""
    import os

    from mirrordimensions.service.sandbox import open_model_routes

    name = "The model is reachable through its route"
    routes = [m for m in plan.models if agent.model in (None, m.name)]
    if agent.model and not routes:
        add(
            name,
            False,
            f"no route called {agent.model!r}",
            "Add it to mirror.yaml (models:) or fix model: in the agent file.",
        )
        return
    if not routes:
        add(name, None, "no model route in mirror.yaml")
        return
    try:
        open_model_routes(plan, os.environ)
    except MirrorError as exc:
        add(name, False, exc.what, exc.fix)
        return
    for route in routes:
        path = "/v1/messages" if route.provider == "anthropic" else "/v1/chat/completions"
        probe = docker.run(
            sandbox.IMAGES["probe"],
            [
                "curl",
                "-sk",
                "-m",
                "20",
                "-o",
                "/dev/null",
                "-w",
                "%{http_code}",
                "--resolve",
                f"{route.host}:443:{plan.addr.gw_lan}",
                "-X",
                "POST",
                "-H",
                "content-type: application/json",
                "-d",
                "{}",
                f"https://{route.host}{path}",
            ],
            network=sandbox.LAN,
        )
        status = probe.output.strip()[-3:]
        if status in ("000", "") or not status.isdigit():
            add(
                f"{name}: {route.name}",
                False,
                f"no answer from {route.host}",
                "Run: mirror up, then check the upstream is running.",
            )
        elif status in ("401", "403"):
            add(
                f"{name}: {route.name}",
                False,
                f"{route.host} refused the credential ({status})",
                f"Check {route.credential_env} holds a valid key.",
            )
        else:
            add(
                f"{name}: {route.name}",
                True,
                f"{route.host} answered {status} with the real credential added at the gateway",
            )
        add(
            f"Provider-hosted tools: {route.name}",
            True,
            {
                "block": "blocked",
                "flag": "forwarded and flagged: coverage incomplete",
                "allow": "allowed, stated in the report",
            }[route.hosted_tools],
        )


def add_browser_check(
    add: Any,
    project: Project,
    docker: Docker,
    plan: sandbox.Plan,
    desk: browser.BrowserPlacement,
    identities: dict[str, Identity],
) -> None:
    """Start the managed browser and its observer, and drive it from the office network
    the way the agent will: DevTools answers at the browser's address, through the observer."""
    name = "The managed browser starts and can be driven"
    ca_pem = (project.state_dir / "ca" / "root-ca.crt").read_bytes()
    try:
        image = browser.ensure_image(docker, ca_pem)
        browser.start(docker, plan, desk, image, [i.password for i in identities.values()])
        reply = ""
        for _ in range(20):  # Chromium is listening within a few seconds
            probe = docker.run(
                sandbox.IMAGES["probe"],
                ["curl", "-sS", "--max-time", "3", f"{desk.cdp_url}/json/version"],
                network=sandbox.LAN,
            )
            reply = probe.output
            if probe.exit_code == 0 and "webSocketDebuggerUrl" in reply:
                break
            time.sleep(1)
        version = next(
            (line.split('"')[3] for line in reply.splitlines() if '"Browser"' in line), ""
        )
        add(
            name,
            bool(version),
            f"{desk.name} at {desk.cdp_url}, {version}" if version else reply[-200:],
            "Run: mirror engine check, then try again; the browser image may need rebuilding.",
        )
    except MirrorError as exc:
        add(name, False, exc.what, exc.fix)
    finally:
        browser.stop(docker, desk)


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
    if agent.mode == "remote":
        add("Remote agents", None, "remote agents arrive in M7.5")
        return checks
    manifest = _manifest(project)
    plan = project_plan(project, manifest)
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
            f"{arch} on an {native} engine: runs emulated, at reduced isolation"
            if native[0] in "aeiou"
            else f"{arch} on a {native} engine: runs emulated, at reduced isolation",
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
    desk = browser.placement(plan, agent.name) if agent.mode == "browser" else None
    try:
        env = (
            browser.environment(agent.env, identities, desk)
            if desk
            else hosted.environment(agent.env, identities)
        )
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
    if desk is not None:
        add_browser_check(add, project, docker, plan, desk, identities)
    injected = " ".join(
        [
            where.name,
            *([desk.name, f"{browser.CDP_ENV}={desk.cdp_url}"] if desk else []),
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
    _model_checks(add, docker, plan, agent)
    channels = (
        "http and WebSocket at the gateway, DNS at the resolvers, refused connections at the engine"
    )
    if desk is not None:
        channels += ", DevTools commands, navigations and screenshots at the browser observer"
    if any(a.is_mcp and a.id in agent.grants for a in plan.apps):
        channels += ", MCP messages and tool calls at the gateway"
    add("Coverage channels report captured", True, channels)
    return checks
