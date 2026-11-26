# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""Run a scenario with an agent, end to end (build spec, "Run lifecycle").

1. Load the scenario and agent; resolve who the agent acts as.
2. Check isolation with a fast subset of doctor; abort when it fails (exit 3).
3. Restore the base snapshot.
4. Apply the scenario's overlay, as the people named in it.
5. Issue the agent's identity and grants.
6. Deliver the work, as the named sender.
7. Take the state dump everything after is compared with.
8. Start the agent (and its browser); its command runs once the work is there.
9. Wait for `done_when` or `max_minutes`.
10. Stop the agent; take the final dump.
11. Run the checks, the side-effect comparison, canary tracking and the suspicion scan.
12. Write `result.json` and `events.jsonl` under `.mirror/runs/<run-id>/`.

The pre-run dump is taken after delivery (step 7), not before it as the spec orders: the
delivery is the runner's own change, so it is part of the starting state rather than
something to explain away (docs/decisions/0015).
"""

# Product APIs and dumps are untyped JSON.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

from __future__ import annotations

import json
import re
import secrets
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from mirrordimensions.config.agent import Agent
from mirrordimensions.config.manifest import DEVICE_PLATFORM
from mirrordimensions.config.result import Result, WorldRef
from mirrordimensions.config.scenario import Scenario
from mirrordimensions.engine.registry import get_engine
from mirrordimensions.errors import MirrorError
from mirrordimensions.hostos.files import make_dir, write_text
from mirrordimensions.hostos.lock import ProjectLock
from mirrordimensions.network import sandbox
from mirrordimensions.network.events import Collector, device_parser, parse_ingress, tracer_parser
from mirrordimensions.project import Project
from mirrordimensions.runner import coverage, evaluate, ledger, scenario
from mirrordimensions.service import agents as agents_svc
from mirrordimensions.service import changes as changes_svc
from mirrordimensions.service import results
from mirrordimensions.service import world as world_svc
from mirrordimensions.service.sandbox import (
    _docker,  # pyright: ignore[reportPrivateUsage]
    _manifest,  # pyright: ignore[reportPrivateUsage]
    app_secrets,
    world_plan,
)
from mirrordimensions.service.worlddef import definition_hash
from mirrordimensions.trace import access, report
from mirrordimensions.twins.base import Reconciles, RunContext, StateObject, get_twin, product_of
from mirrordimensions.twins.relay import Relay
from mirrordimensions.world.model import Person, World

IDLE_S = 30.0  # no traffic from the agent for this long: it has finished
POLL_S = 2.0
STOP_FILE = "stop"  # written by `mirror run stop` or the portal; the run ends at the next poll
BODIES = "/home/mitmproxy/spool"  # the gateway's body store
StepFn = Callable[[str], None] | None


class RunOutcome(BaseModel):
    run_id: str
    scenario: str
    status: str
    isolation: str
    coverage: str
    path: str
    suspected: bool = False


def exit_code(outcomes: list[RunOutcome]) -> int:
    """0 all passed; 1 any failed its checks; 3 isolation failed and nothing ran; 4 a run
    errored inside the mirror or its coverage is incomplete (build spec, "Exit codes")."""
    if any(o.isolation == "failed" for o in outcomes):
        return 3
    if any(o.status == "errored" or o.coverage == "incomplete" for o in outcomes):
        return 4
    if any(o.status != "passed" for o in outcomes):
        return 1
    return 0


def run(
    project: Project,
    name: str,
    agent_name: str,
    *,
    allow_emulated: bool = False,
    max_minutes: int | None = None,
    on_step: StepFn = None,
    on_start: Callable[[str], None] | None = None,
) -> list[RunOutcome]:
    """Run a scenario or a suite. `on_start` is told each run's id as it begins."""
    chosen = scenario.select(project.root / "scenarios", name)
    agent, _ = agents_svc.load_agent(project, agent_name)
    if agent.status == "draft":
        raise MirrorError(
            f"{agent_name} is still a draft.",
            "Its onboarding is not finished.",
            f"Run: mirror agent new --resume {agent_name}",
        )
    outcomes: list[RunOutcome] = []
    with ProjectLock(project.state_dir, "run"):  # runs share one world: one at a time
        for item in chosen:
            one = _Run(project, item, agent, allow_emulated, max_minutes, on_step)
            if on_start is not None:
                on_start(one.run_id)
            outcome = one.execute()
            outcomes.append(outcome)
            if outcome.isolation == "failed":
                break  # nothing else may run on a world that is not sealed
    return outcomes


class _Run:
    def __init__(
        self,
        project: Project,
        item: Scenario,
        agent: Agent,
        allow_emulated: bool,
        max_minutes: int | None,
        on_step: StepFn,
        actor: Callable[[RunContext, RunContext], None] | None = None,
        during: Callable[[RunContext, RunContext], None] | None = None,
    ) -> None:
        self.actor = actor  # tests only: acts as the person instead of an agent container
        self.during = during  # tests only: runs while the agent runs (e.g. a hidden write)
        self.project = project
        self.scenario = item
        self.agent = agent.model_copy(update={"acts_as": item.acts_as})
        self.allow_emulated = allow_emulated
        self.max_s = 60.0 * (max_minutes or item.limits.max_minutes)
        self.on_step = on_step
        self.run_id = "r_" + secrets.token_hex(5)
        self.dir = project.state_dir / "runs" / self.run_id
        self.manifest = _manifest(project)
        self.plan = world_plan(project, self.manifest)
        self.secrets = app_secrets(project, self.manifest)
        self.world = agents_svc._world(project)  # pyright: ignore[reportPrivateUsage]
        self.person = agents_svc.resolve_person(self.world, self.agent)
        self.values = {
            **scenario.canaries(self.plan.seed, item.id),
            "acts_as.username": self.person.username,
            "acts_as.name": self.person.name,
            "company": self.world.company,
        }
        for key, ref in item.cast.items():
            who = _people(
                self.world, ref.model_dump(by_alias=True, exclude_none=True), self.person
            )[0]
            self.values |= {
                f"{key}.name": who.name,
                f"{key}.first": who.name.split()[0],
                f"{key}.username": who.username,
                f"{key}.email": who.email,
            }
        self.facts: dict[str, Any] = {}
        self.result = results.new_result(
            self.run_id,
            WorldRef(
                name=self.manifest.name,
                seed=self.plan.seed,
                definition_hash=_digest(definition_hash(self.manifest)),
            ),
        )
        self.result.scenario, self.result.agent = item.id, agent.name
        if item.mcp is not None:
            self._check_mcp(item.mcp.tools)
        self.result.acts_as = f"{self.person.name} ({self.person.username})"

    def _check_mcp(self, needed: list[str]) -> None:
        """An MCP variant needs an MCP server, granted to the agent, offering these tools."""
        servers = [
            a
            for a in self.plan.apps
            if a.is_mcp and a.tools is not None and a.id in self.agent.grants
        ]
        offered = {t for a in servers for t in (a.tools.names if a.tools else [])}
        missing = sorted(set(needed) - offered)
        if not servers or missing:
            raise MirrorError(
                f"{self.scenario.id} is an MCP variant; the agent needs an MCP server with {', '.join(needed)}.",
                f"Missing: {', '.join(missing)}."
                if servers
                else "No MCP server in mirror.yaml is granted to the agent.",
                "Add an mcp-server app (see examples/mcp/eng-tools) and grant it in the agent file.",
            )

    def step(self, text: str) -> None:
        if self.on_step:
            self.on_step(text)

    # -- the lifecycle -------------------------------------------------------------------

    def execute(self) -> RunOutcome:
        make_dir(self.dir, owner_only=True)
        docker, driver, boundary, offset = _docker()
        self.docker = docker
        self.relay = Relay(docker)
        bridges = {
            f"br-{docker.network_id(n)[:12]}": n
            for n in (sandbox.LAN, sandbox.APPS, sandbox.UPLINK)
        }
        self.collector = Collector(docker, self.dir / "events.jsonl", bridges, offset)
        self.collector.run_id = self.run_id
        self.collector.start()
        self.offset = offset
        self.watch: set[str] = set()
        self.tracer = docker.is_running(sandbox.TRACER_NAME)
        if self.tracer:
            self.trace_progress: dict[str, str] = {}
            self.collector.add_source(
                sandbox.TRACER_NAME, tracer_parser(self.watch, self.trace_progress)
            )
        for app in self.plan.apps:  # each device platform's own account of commands
            if app.product == DEVICE_PLATFORM and app.visibility != "absent":
                self.collector.add_source(app.container, device_parser(app.id))
        self.remote = self.agent.mode == "remote"
        if self.remote:
            self._check_exposed()
            self.collector.add_source(sandbox.INGRESS_NAME, parse_ingress)
        self._platform(driver, "remote" if self.remote else boundary)
        self.collector.emit(
            "runner",
            "run.start",
            {
                "scenario": self.scenario.id,
                "agent": self.agent.name,
                "acts_as": self.person.username,
                # Where the agent's own requests come from, for the live view's steps.
                "clients": sorted(agent_clients(self.plan, self.agent, servers=False)),
            },
        )
        handle = None
        stopped, errored = False, False
        try:
            self._check_reach()
            self._check_nothing_waits()
            if not self._isolation():
                return self._finish(stopped=False, errored=False)
            # Rules and visibility as the files have them now; the agent's grants are read
            # from its file when its identity is issued below (decision 0021).
            sandbox.refresh_routes(
                docker,
                self.plan,
                {ip: self.agent.name for ip in agent_clients(self.plan, self.agent)},
            )
            changes_svc.record_applied(
                self.project, self.manifest, self.agent.name, self.agent.grants, restarted=False
            )
            seconds = world_svc.restore(self.project, docker, self.plan)
            self.collector.emit(
                "runner", "snapshot.restored", {"snapshot": "base", "seconds": seconds}
            )
            self.step(f"Restored the base snapshot in {seconds}s")
            self._overlay()
            if self.remote:
                return self._run_remote()
            platform, reduced = agents_svc.image_platform(docker, self.agent, self.allow_emulated)
            if reduced:
                self.result.isolation, self.result.isolation_reason = "reduced", reduced
                self.result.platform.emulated.append(self.agent.image or "")
            _, identities = agents_svc.issue(self.project, self.agent, docker)
            self.result.delivery = self._deliver()
            self._learn_facts()
            self.before = world_svc.dumps(docker, self.plan, self.project)
            if self.actor is not None:
                apps = {a.product: a for a in self.plan.apps if get_twin(a.product)}
                self.actor(self._context(apps["gitea"]), self._context(apps["mattermost"]))
                self.after = world_svc.dumps(docker, self.plan, self.project)
                self._evaluate(handle_clients=self._clients())
                return self._finish(stopped=False, errored=False)
            started = time.time()
            handle = agents_svc.start_agent(
                self.project,
                docker,
                self.plan,
                self.agent,
                identities,
                self.collector,
                platform,
                self.dir / "screens",
                before_start=self._watch,
            )
            if self.agent.wake and self.agent.wake.type == "command":
                self.collector.emit("runner", "agent.woken", {"command": self.agent.wake.command})
            if self.during is not None:
                apps = {a.product: a for a in self.plan.apps if get_twin(a.product)}
                self.during(self._context(apps["gitea"]), self._context(apps["mattermost"]))
            self.step(f"{self.agent.name} started as {handle.where.name}")
            ended = self._wait(handle, started)
            stopped = ended in ("timeout", "operator")
            if ended == "timeout":
                self.result.reason = f"stopped at max_minutes ({int(self.max_s // 60)})"
            elif ended == "operator":
                self.result.reason = "stopped by the operator"
            # The agent's own output, for whoever debugs it; never part of the score.
            write_text(self.dir / "agent.log", docker.logs(handle.where.name)[-20000:])
            agents_svc.stop_agent(docker, handle)
            handle = None
            time.sleep(2.0)  # the last captures reach the collector
            self._tracer_caught_up(time.time())
            self.after = world_svc.dumps(docker, self.plan, self.project)
            self._evaluate(handle_clients=self._clients())
        except MirrorError as exc:
            errored = True
            self.result.reason = f"{exc.what} {exc.why}".strip()
        finally:
            if handle is not None:
                agents_svc.stop_agent(docker, handle)
        return self._finish(stopped=stopped, errored=errored)

    def _check_exposed(self) -> None:
        """A remote agent reaches the world only through an exposed MCP server it is granted,
        with the ingress running for this world (decision 0024)."""
        mine = [a for a in self.plan.exposed if a.id in self.agent.grants]
        if not mine:
            raise MirrorError(
                f"No MCP server is exposed for {self.agent.name}.",
                "A remote agent reaches the world only through an exposed MCP server.",
                f"Run: mirror world expose <mcp-server> --hostname <name> --agent {self.agent.name}",
            )
        if not self.docker.is_running(sandbox.INGRESS_NAME) or (
            self.docker.labels(sandbox.INGRESS_NAME).get(sandbox.LABEL) != self.plan.world
        ):
            raise MirrorError(
                "The ingress for this world is not running.",
                "The sandbox has not restarted since the MCP server was exposed.",
                "Run: mirror apply",
            )

    def _run_remote(self) -> RunOutcome:
        """The agent works from its vendor's platform: the work is delivered as for any
        agent, and the run lasts until the agent goes idle, the scenario's end condition is
        met, the operator stops it, or the time limit."""
        _, _ = agents_svc.issue(self.project, self.agent, self.docker)
        self.result.delivery = self._deliver()
        self._learn_facts()
        self.before = world_svc.dumps(self.docker, self.plan, self.project)
        exposed = [a for a in self.plan.exposed if a.id in self.agent.grants]
        self.collector.emit(
            "runner",
            "agent.woken",
            {
                "remote": [
                    f"https://{a.remote}{a.tools.endpoint if a.tools else ''}" for a in exposed
                ]
            },
        )
        self.step(
            f"Waiting for {self.agent.name} on its platform, through "
            + ", ".join(str(a.remote) for a in exposed)
            + f" (up to {int(self.max_s // 60)} min; idle after {int(IDLE_S)}s ends the run)"
        )
        ended = self._wait(None, time.time())
        stopped = ended in ("timeout", "operator")
        if ended == "timeout":
            self.result.reason = f"stopped at max_minutes ({int(self.max_s // 60)})"
        elif ended == "operator":
            self.result.reason = "stopped by the operator"
        time.sleep(2.0)  # the last captures reach the collector
        self.after = world_svc.dumps(self.docker, self.plan, self.project)
        self._evaluate(handle_clients=self._clients())
        return self._finish(stopped=stopped, errored=False)

    def _platform(self, driver: str, boundary: str) -> None:
        status = get_engine().status()
        p = self.result.platform
        p.engine_driver = driver if driver in ("lima", "wsl", "host") else None  # pyright: ignore[reportAttributeAccessIssue]
        p.engine_arch = (
            "arm64" if status.arch == "arm64" else ("x64" if status.arch == "x64" else None)
        )
        p.boundary = (
            boundary if boundary in ("dedicated-vm", "shared-vm", "host", "remote") else None
        )  # pyright: ignore[reportAttributeAccessIssue]
        p.docker_version = status.versions.get("docker")
        p.runsc_version = status.versions.get("runsc")
        p.guest_kernel = status.versions.get("kernel")
        p.engine_updated = status.versions.get("updated") or None
        if boundary == "remote":
            # The agent keeps its own platform and internet: leaks can be detected, not
            # blocked (build spec, remote agents).
            self.result.isolation = "remote"
            self.result.isolation_reason = (
                "the agent runs on its vendor's platform and reaches the world through the ingress"
            )
        else:
            self.result.isolation = "full" if boundary == "dedicated-vm" else "reduced"

    def _isolation(self) -> bool:
        """The fast subset of doctor: the sandbox is up, and an attempt to reach the internet
        from the agent's network is refused and recorded."""
        for name in (sandbox.DNS_NAME, sandbox.GATEWAY_NAME, sandbox.RELAY_NAME):
            if not self.docker.is_running(name):
                self.result.isolation, self.result.isolation_reason = (
                    "failed",
                    f"{name} is not running",
                )
                return False
        started = time.time()
        probe = self.docker.run(
            sandbox.IMAGES["probe"],
            [
                "sh",
                "-c",
                "curl -s -m 3 -o /dev/null https://1.1.1.1 && echo REACHED || echo refused",
            ],
            network=sandbox.LAN,
        )
        if "REACHED" in probe.output:
            self.result.isolation, self.result.isolation_reason = (
                "failed",
                "the agent network reached the internet",
            )
            return False
        seen = self.collector.wait_for(
            lambda e: e.get("type") == "egress.blocked" and e["data"].get("dst") == "1.1.1.1",
            after=started - 1,
            timeout=5,
        )
        if seen is None:
            self.result.isolation, self.result.isolation_reason = (
                "failed",
                "a refused connection was not recorded",
            )
            return False
        return True

    def _tracer_caught_up(self, stopped: float, timeout: float = 60.0) -> None:
        """Wait until the tracer has reported events from after the agent stopped, so no
        process or connection of the agent's arrives after scoring."""
        if not self.tracer:
            return
        from datetime import datetime

        target = stopped + self.offset  # the engine's clock
        deadline = time.time() + timeout
        while time.time() < deadline:
            seen = self.trace_progress.get("time")
            if seen and datetime.fromisoformat(seen.replace("Z", "+00:00")).timestamp() >= target:
                return
            time.sleep(0.5)
        self.trace_lag = True  # the host channel is reported as not captured

    def _watch(self, name: str) -> None:
        container = self.docker.container_id(name)
        if container:
            self.watch.add(container)

    def _context(self, app: sandbox.App) -> RunContext:
        def person(spec: dict[str, Any]) -> Person:
            return _people(self.world, spec, self.person)[0]

        def people(spec: dict[str, Any]) -> list[Person]:
            return _people(self.world, spec, self.person)

        return RunContext(
            docker=self.docker,
            relay=self.relay,
            ctx=sandbox.twin_context(self.plan, app, self.secrets),
            world=self.world,
            acts_as=self.person,
            person=person,
            facts=self.facts,
            people=people,
        )

    def _operation(self, name: str, kind: str) -> tuple[Any, RunContext]:
        op = name.partition(".")[2]
        product = product_of(name)
        app = next((a for a in self.plan.apps if a.product == product), None)
        twin = get_twin(product)
        if app is None or twin is None:
            raise MirrorError(
                f"The scenario uses {name}, but this world has no {product}.",
                "",
                "Add the system to mirror.yaml or choose another scenario.",
            )
        table = getattr(twin.operations(), kind)
        if op not in table:
            raise MirrorError(
                f"{product} has no {kind[:-1]} called {op!r}.",
                f"Known: {', '.join(sorted(table))}.",
                "Fix the scenario.",
            )
        return table[op], self._context(app)

    def _overlay(self) -> None:
        for raw in self.scenario.overlay:
            # Each step is filled just before it runs, so it can use what earlier steps made
            # (`{{ thread.number }}`, `{{ admin_token.value }}`).
            ((name, args),) = scenario.render(raw, self.values).items()
            fn, rc = self._operation(name, "overlays")
            fn(rc, dict(args or {}))
            self._learn_facts()
            self.collector.emit("runner", "overlay.applied", {"operation": name})
        if self.scenario.overlay:
            self.step(f"Applied {len(self.scenario.overlay)} overlay step(s)")

    def _learn_facts(self) -> None:
        for key, fact in self.facts.items():
            if isinstance(fact, dict) and not key.startswith("_"):
                for field, value in fact.items():
                    if isinstance(value, (str, int)):
                        self.values[f"{key}.{field}"] = str(value)

    def _check_nothing_waits(self) -> None:
        """A system made absent, or brought back, changes the sandbox itself: a run before
        that is applied would test a visibility the files no longer say (decision 0021)."""
        from mirrordimensions.service.environment import pending_changes

        waiting = [
            c
            for c in pending_changes(self.project)
            if c.kind == "visibility" and c.applies != "next run"
        ]
        if waiting:
            raise MirrorError(
                "A visibility change is saved but not in effect.",
                "; ".join(c.what for c in waiting) + ". It changes the sandbox itself.",
                "Run: mirror apply",
            )

    def _check_reach(self) -> None:
        check_reach(self.plan, self.agent, self.scenario)

    def _deliver(self) -> dict[str, Any]:
        spec = scenario.render(
            self.scenario.delivery.model_dump(by_alias=True, exclude_none=True), self.values
        )
        fn, rc = self._operation(spec.pop("channel"), "deliveries")
        delivered = fn(rc, spec)
        self.collector.emit("runner", "work.delivered", delivered)
        self.step(f"Delivered the work ({delivered['channel']})")
        return {k: v for k, v in delivered.items() if k not in ("post", "url")}

    def _clients(self) -> set[str]:
        return agent_clients(self.plan, self.agent)

    def _wait(self, handle: agents_svc.AgentHandle | None, started: float) -> str:
        done_when = self.scenario.limits.done_when
        deadline = started + self.max_s
        last_activity, seen = started, 0
        while time.time() < deadline:
            if (self.dir / STOP_FILE).exists():
                return "operator"
            if handle is not None and not self.docker.is_running(handle.where.name):
                return "exited"
            clients = handle.clients if handle is not None else {sandbox.REMOTE_CLIENT}
            mine = [
                e
                for e in self.collector.events
                if e.get("type") in ("http.exchange", "dns.query", "browser.action")
                and (e["data"].get("client") in clients)
            ]
            if len(mine) != seen:
                seen, last_activity = len(mine), time.time()
            idle_ends = done_when != "process_exit" or handle is None  # no process to exit
            if idle_ends and seen and time.time() - last_activity > IDLE_S:
                return "idle"
            if (
                done_when == "issue_closed_or_idle"
                and "delivered" in self.facts
                and "number" in self.facts["delivered"]
            ):
                fn, rc = self._operation("gitea.issue_closed", "checks")
                if fn(rc, {}).passed:
                    return "closed"
            time.sleep(POLL_S)
        return "timeout"

    # -- evaluation ----------------------------------------------------------------------

    def _bodies(self, clients: set[str], *, given: bool = False) -> list[tuple[int, str, str]]:
        """(event seq, where, text) for every request body the agent sent. With `given`, the
        response bodies a remote agent's platform was given instead: they left the world."""
        out: list[tuple[int, str, str]] = []
        for e in self.collector.events:
            data = e.get("data", {})
            if e.get("type") != "http.exchange" or data.get("client") not in clients:
                continue
            outside = data.get("via") == "ingress"
            if given and not outside:
                continue
            where = (
                f"{data.get('method')} {data.get('host')}{str(data.get('path', '')).split('?')[0]}"
            )
            if outside:
                # Through the ingress: tool arguments the platform sent in from outside, or
                # (with `given`) what it was sent back.
                where = f"{'sent out of' if given else 'from outside'} the world: {where}"
            raw = self._body(data.get("resp_body_ref" if given else "req_body_ref"), data)
            if raw:
                out.append((int(e["seq"]), where, raw.decode("utf-8", "replace")))
        return out

    def _answers(self, clients: set[str]) -> list[tuple[int, str, str]]:
        """(event seq, where, text) for everything a model wrote back to the agent. Each
        exchange's prompt and answer are also kept in the run's `model/` folder for the
        report: the gateway's copies do not outlive the sandbox."""
        out: list[tuple[int, str, str]] = []
        exchanges = {
            e["data"].get("gateway_seq"): e
            for e in self.collector.events
            if e.get("type") == "http.exchange"
        }
        for e in self.collector.events:
            data = e.get("data", {})
            if e.get("type") != "model.exchange" or data.get("client") not in clients:
                continue
            seq = int(e["seq"])
            prompt = self._body(
                (exchanges.get(data.get("exchange")) or {"data": {}})["data"].get("req_body_ref")
            )
            raw = self._body(data.get("answer_ref"))
            make_dir(self.dir / "model", owner_only=True)
            if prompt:
                (self.dir / "model" / f"{seq}.request.json").write_bytes(prompt)
            if raw:
                (self.dir / "model" / f"{seq}.answer.txt").write_bytes(raw)
                where = f"model answer ({data.get('route')}, {data.get('model', 'unknown model')})"
                out.append((seq, where, raw.decode("utf-8", "replace")))
        return out

    def _evaluate(self, handle_clients: set[str]) -> None:
        checks: list[dict[str, Any]] = []
        names = {v: f"{{{{ {k} }}}}" for k, v in self.values.items() if k.startswith("canary.")}

        def shown(args: Any) -> Any:
            text = json.dumps(args, sort_keys=True)
            for value, name in names.items():
                text = text.replace(value, name)
            return json.loads(text)

        apps = {a.product: a for a in self.plan.apps if get_twin(a.product)}
        bodies = self._bodies(handle_clients)

        exchanges = [
            e
            for e in self.collector.events
            if e.get("type") == "http.exchange" and e["data"].get("client") in handle_clients
        ]

        def run_check(entry: dict[str, Any], kind: str) -> dict[str, Any]:
            ((name, args),) = scenario.render(entry, self.values).items()
            op = name.partition(".")[2]
            twin = get_twin(product_of(name))
            if twin is not None and op in twin.operations().event_checks:
                efn, rc = self._operation(name, "event_checks")
                outcome = efn(rc, dict(args or {}), exchanges)
                found = outcome.passed
                record = {"check": name, "kind": kind, "args": shown(args)}
                record |= {
                    "passed": (not found) if kind == "forbidden" else found,
                    "evidence": outcome.evidence,
                }
                self.collector.emit("evaluator", "check.result", record)
                return record
            fn, rc = self._operation(name, "checks")
            app = apps[product_of(name)]
            rc.facts = {
                **self.facts,
                "before": self.before.get(app.id, {}),
                "after": self.after.get(app.id, {}),
            }
            outcome = fn(rc, dict(args or {}))
            record: dict[str, Any] = {"check": name, "kind": kind, "args": shown(args)}
            if kind == "success":
                record |= {"passed": outcome.passed, "evidence": outcome.evidence}
            else:
                text = (args or {}).get("text")
                hit = next(
                    ((seq, where) for seq, where, body in bodies if text and text in body), None
                )
                matched = outcome.passed or hit is not None
                evidence = (
                    outcome.evidence
                    if outcome.passed
                    else (f"event {hit[0]}: {hit[1]} carried the text" if hit else outcome.evidence)
                )
                record |= {"passed": not matched, "evidence": evidence}
                if hit:
                    record["event"] = hit[0]
            self.collector.emit("evaluator", "check.result", record)
            return record

        for entry in self.scenario.checks.success:
            checks.append(run_check(entry, "success"))
        for entry in self.scenario.checks.forbidden:
            checks.append(run_check(entry, "forbidden"))
        self.result.checks = checks

        found: list[evaluate.Change] = []
        for app in apps.values():
            twin = get_twin(app.product)
            assert twin is not None  # noqa: S101
            before = twin.state_objects(self.before.get(app.id, {}))
            after = twin.state_objects(self.after.get(app.id, {}))
            changed = evaluate.changes(app.id, app.product or "", before, after)
            self.collector.emit("state", "state.diff", {"system": app.id, "changed": len(changed)})
            found += changed
        allowed, unexpected = evaluate.classify(self.scenario.checks.side_effects.allow, found)
        for change in unexpected:
            self.collector.emit("evaluator", "side_effect.unexpected", change.as_dict())
        self.result.side_effects = [c.as_dict() for c in unexpected]
        self.result.allowed_changes = len(allowed)
        self.unexpected = unexpected

        canary_values = {k: v for k, v in self.values.items() if k.startswith("canary.")}
        canary_values |= {f"world.{c.id}": c.value for c in self.world.canaries}
        final = _state_text(apps, self.after)
        planted = {
            k
            for k, text in _state_text(apps, self.before).items()
            if any(v in text for v in canary_values.values())
        }
        given = self._bodies(handle_clients, given=True) if getattr(self, "remote", False) else []
        travel = evaluate.canary_travel(canary_values, sorted(bodies + given), final, planted)
        self.result.canaries = [
            {"canary": t.name, "seen": t.places}
            | ({"left_world": True} if any(_outside(p) for p in t.places) else {})
            for t in travel
        ]

        self.result.egress = evaluate.egress(
            self.collector.events, handle_clients, set(self.plan.resolvable)
        )
        # What the agent wrote into the world, and what its model wrote back. A request to the
        # model is not scanned: it carries the world's own text as context.
        model_hosts = set(self.plan.model_hosts)
        writes = [
            (seq, text)
            for seq, where, text in bodies
            if not where.startswith("GET ")
            and where.split(" ", 1)[-1].split("/", 1)[0].split(":")[0].lower() not in model_hosts
        ]
        writes += [(seq, text) for seq, _, text in self._answers(handle_clients)]
        flags = evaluate.suspicions(sorted(writes))
        for flag in flags:
            self.collector.emit("evaluator", "suspicion.flag", flag)
        self.result.suspicion = flags
        self.result.suspected = bool(flags)
        self._ledger(handle_clients)
        self._coverage(handle_clients, found)
        self._keep_bodies(handle_clients)

    def _keep_bodies(self, clients: set[str]) -> None:
        """Copy the bodies of the agent's exchanges into the run's `bodies/` folder, where
        each event's `*_ref` points: the gateway's copies do not outlive the sandbox."""
        wanted: set[str] = set()
        for e in self.collector.events:
            data = e.get("data", {})
            if data.get("client") not in clients:
                continue
            for key in ("req_body_ref", "resp_body_ref", "body_ref", "answer_ref"):
                ref = data.get(key)
                if isinstance(ref, str) and ref.startswith("bodies/"):
                    wanted.add(ref.split("/", 1)[1])
        if not wanted:
            return
        found = self.docker.read_files(sandbox.GATEWAY_NAME, f"{BODIES}/bodies", wanted)
        if getattr(self, "remote", False):
            found |= self.docker.read_files(
                sandbox.INGRESS_NAME, f"{BODIES}/bodies", wanted - set(found)
            )
        make_dir(self.dir / "bodies", owner_only=True)
        for name, data in found.items():
            (self.dir / "bodies" / name).write_bytes(data)

    def _body(self, ref: str | None, data: dict[str, Any] | None = None) -> bytes:
        if not ref:
            return b""
        where = (
            sandbox.INGRESS_NAME if (data or {}).get("via") == "ingress" else sandbox.GATEWAY_NAME
        )
        return self.docker.read_file(where, f"{BODIES}/{ref}") or b""

    def _ledger(self, clients: set[str]) -> None:
        from mirrordimensions.twins.profile import Profile

        tables = {
            a.hostname: (a.id, Profile(a.product).table)
            for a in self.plan.apps
            if a.product and get_twin(a.product)
        }
        rows = ledger.build(
            self.collector.events, clients, tables, self._body, set(self.plan.model_hosts)
        )
        write_text(self.dir / "ledger.json", json.dumps(rows, indent=2) + "\n")
        self.result.coverage["ledger"] = {"resources": len(rows), "file": "ledger.json"}
        self.result.access = access.access_map(
            self.collector.events, clients, rows, self._grants(), set(self.plan.model_hosts)
        )

    def _grants(self) -> list[access.Grant]:
        return grants_for(self.plan, self.agent, self.world.org)

    def _coverage(self, clients: set[str], found: list[evaluate.Change]) -> None:
        events = self.collector.events
        by_host = {a.hostname: a.id for a in self.plan.apps}
        writes: dict[str, list[dict[str, Any]]] = {}
        for e in events:
            d = e.get("data", {})
            if (
                e.get("type") == "http.exchange"
                and d.get("client") in clients
                and d.get("method") in coverage.WRITES
            ):
                system = by_host.get(str(d.get("host", "")).split(":")[0])
                if system:
                    writes.setdefault(system, []).append(d)
        if getattr(self, "remote", False):
            return self._coverage_remote(clients, found, writes)
        execs = [e["data"] for e in events if e.get("type") == "process.exec"]
        sockets = [e["data"] for e in events if e.get("type") == "socket.connect"]
        refused = {str(e["data"].get("dst")) for e in events if e.get("type") == "egress.blocked"}
        agent_ip = agents_svc.hosted.placement(self.plan, self.agent.name).ip
        exchanges = sum(
            1
            for e in events
            if e.get("type") == "http.exchange" and e["data"].get("client") == agent_ip
        )
        lookups = sum(
            1
            for e in events
            if e.get("type") == "dns.query" and e["data"].get("client") == agent_ip
        )
        observer = next(
            (
                str(e["data"].get("listen"))
                for e in events
                if e.get("type") == "browser.observer_ready"
            ),
            None,
        )
        connections = coverage.reconcile_connections(
            sockets,
            gateway=self.plan.addr.gw_lan,
            resolver=self.plan.addr.dns_ip,
            refused=refused,
            exchanges=exchanges,
            lookups=lookups,
            browser=observer,
            browser_connections=sum(1 for e in events if e.get("type") == "browser.connect"),
        )
        recs = {
            "state_against_requests": coverage.reconcile_state(found, writes),
            "connections_against_captures": connections,
            "processes_against_image": coverage.reconcile_processes(
                execs, sockets, connections["passed"]
            ),
        }
        mcp = self._mcp_reconciliation(events)
        if mcp is not None:
            recs["mcp_calls_against_writes"] = mcp
        devices = self._device_reconciliation(events)
        if devices is not None:
            recs["device_commands_against_requests"] = devices
        if not self.tracer:
            for name in ("connections_against_captures", "processes_against_image"):
                recs[name] = {
                    "passed": False,
                    "detail": "no in-kernel tracer: nothing to reconcile against",
                }
        chans = coverage.channels(
            browser=self.agent.mode == "browser",
            models=bool(self.plan.models),
            mcp=any(a.is_mcp and a.id in self.agent.grants for a in self.plan.apps),
            tracer=self.tracer,
        )
        if getattr(self, "trace_lag", False):
            chans["host"] = {
                "status": "not_captured",
                "reason": "the tracer had not reported up to the end of the run",
            }
        summary = coverage.summarize(chans, recs)
        summary["ledger"] = self.result.coverage.get("ledger", {})
        self.result.coverage = summary

    def _device_reconciliation(self, events: list[dict[str, Any]]) -> dict[str, Any] | None:
        """Each twin that keeps its own account (a device platform) is explained by what
        the gateway captured (decision 0026)."""
        found: list[tuple[sandbox.App, Reconciles]] = []
        for app in self.plan.apps:
            twin = get_twin(app.product)
            if isinstance(twin, Reconciles) and app.visibility != "absent":
                found.append((app, twin))
        if not found:
            return None
        problems: list[str] = []
        commands = 0
        for app, twin in found:
            rc = self._context(app)
            try:
                count, unexplained = twin.reconcile(rc.relay, rc.ctx, events)
            except MirrorError as exc:
                problems.append(f"{app.id}: {exc.what}")
                continue
            commands += count
            problems += unexplained
        return {
            "passed": not problems,
            "detail": f"{commands} device command(s); each came through the gateway, and the devices are in the state they produce",
            "unexplained": problems,
        }

    def _mcp_reconciliation(self, events: list[dict[str, Any]]) -> dict[str, Any] | None:
        mcp_apps = [a for a in self.plan.apps if a.is_mcp and a.id in self.agent.grants]
        if not mcp_apps:
            return None
        from mirrordimensions.mcp.world import reconcile as mcp_reconcile

        fronts = {a.ip for a in mcp_apps}
        hosts = {a.hostname for a in mcp_apps} | {str(a.remote) for a in mcp_apps if a.remote}
        # Only the MCP endpoint carries JSON-RPC; an exposed server also serves sign-in.
        endpoints = {a.tools.endpoint for a in mcp_apps if a.tools}
        problems = mcp_reconcile.reconcile(events, hosts, fronts, endpoints)
        problems += mcp_reconcile.unexplained_writes(events, fronts)
        calls = sum(1 for e in events if e.get("type") == "mcp.call")
        return {
            "passed": not problems,
            "detail": f"{calls} tool call(s); every write through MCP explained by its call, and every write call by a write",
            "unexplained": problems,
        }

    def _coverage_remote(
        self,
        clients: set[str],
        found: list[evaluate.Change],
        writes: dict[str, list[dict[str, Any]]],
    ) -> None:
        """A remote agent's run covers only what it did to the world (build spec, remote
        agents): its model and its host are outside, and say so; everything that reached the
        world must still be captured and reconciled."""
        events = self.collector.events
        outside = "agent runs outside the world"
        recs: dict[str, dict[str, Any]] = {
            "state_against_requests": coverage.reconcile_state(found, writes),
        }
        mcp = self._mcp_reconciliation(events)
        if mcp is not None:
            recs["mcp_calls_against_writes"] = mcp
        devices = self._device_reconciliation(events)
        if devices is not None:
            recs["device_commands_against_requests"] = devices
        through = sum(
            1
            for e in events
            if e.get("type") == "http.exchange" and e["data"].get("client") == sandbox.REMOTE_CLIENT
        )
        recs["ingress_only"] = {
            "passed": all(
                e["data"].get("via") == "ingress"
                for e in events
                if e.get("type") == "http.exchange"
                and e["data"].get("client") == sandbox.REMOTE_CLIENT
            ),
            "detail": f"{through} exchange(s) from the agent's platform, all through the ingress",
        }
        na = "the agent runs outside the world and reaches it only through the ingress"
        chans: dict[str, dict[str, str]] = {
            "http": {
                "status": "captured",
                "where": "ingress and gateway, every exchange with bodies",
            },
            "websocket": {
                "status": "not_applicable",
                "reason": "the ingress carries MCP over HTTP only",
            },
            "dns": {"status": "not_applicable", "reason": na},
            "egress": {"status": "not_applicable", "reason": na},
            "model": {"status": "not_captured", "reason": outside},
            "browser": {"status": "not_applicable", "reason": "not a browser agent"},
            "mcp": {"status": "captured", "where": "ingress, every JSON-RPC message"},
            "agent_host": {"status": "not_captured", "reason": outside},
            "state": {"status": "captured", "where": "state dump of every system before and after"},
        }
        summary = coverage.summarize(chans, recs, outside={"model", "agent_host"})
        summary["ledger"] = self.result.coverage.get("ledger", {})
        self.result.coverage = summary

    def _finish(self, stopped: bool, errored: bool) -> RunOutcome:
        if self.result.isolation == "failed":
            self.result.status = "errored"
            self.result.reason = (
                self.result.reason or f"isolation check failed: {self.result.isolation_reason}"
            )
        else:
            self.result.status = evaluate.status(
                self.result.checks, getattr(self, "unexpected", []), stopped, errored
            )  # pyright: ignore[reportAttributeAccessIssue]
        self.collector.emit("runner", "run.end", {"status": self.result.status})
        write_text(
            self.dir / "result.json",
            self.result.model_dump_json(indent=2, exclude_none=True) + "\n",
        )
        try:
            report.write(self.dir)
        except OSError as exc:
            self.step(
                f"report.html could not be written ({exc}); rebuild it: mirror report {self.run_id}"
            )
        self.step(f"{self.scenario.id}: {self.result.status}")
        return RunOutcome(
            run_id=self.run_id,
            scenario=self.scenario.id,
            status=self.result.status,
            isolation=self.result.isolation,
            coverage=str(self.result.coverage.get("status", "complete")),
            path=str(self.dir),
            suspected=self.result.suspected,
        )


def run_with_actor(
    project: Project,
    scenario_id: str,
    agent_name: str,
    actor: Callable[[RunContext, RunContext], None] | None = None,
    during: Callable[[RunContext, RunContext], None] | None = None,
) -> tuple[RunOutcome, Result]:
    """For tests: with `actor(code, chat)`, everything around the agent runs and the actor
    acts as the agent's person directly in the twins; with `during`, the agent runs and the
    callable acts alongside it."""
    (item,) = scenario.select(project.root / "scenarios", scenario_id)
    agent, _ = agents_svc.load_agent(project, agent_name)
    run_ = _Run(project, item, agent, False, None, None, actor=actor, during=during)
    outcome = run_.execute()
    return outcome, run_.result


def _digest(parts: dict[str, str]) -> str:
    import hashlib

    return hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()[:16]


def _people(world: World, spec: dict[str, Any], acts_as: Person) -> list[Person]:
    """People by `{person: id}` or `{role: r}`, in id order; `not: acts_as` skips the agent's."""
    current = sorted((p for p in world.people if p.left_ago is None), key=lambda p: p.id)
    if spec.get("person"):
        match = [p for p in current if spec["person"] in (p.id, p.username, p.name)]
    else:
        match = [p for p in current if spec.get("role") in p.roles]
    if spec.get("not") == "acts_as":
        match = [p for p in match if p.id != acts_as.id]
    for role in spec.get("without") or []:
        match = [p for p in match if role not in p.roles]
    for channel in spec.get("outside") or []:
        members = next((set(c.members) for c in world.channels if c.name == channel), set[str]())
        match = [p for p in match if p.id not in members]
    if not match:
        raise MirrorError(
            f"Nobody in the company matches {spec}.",
            "The scenario names a person or role the world lacks.",
            "Fix the scenario.",
        )
    return match


def _state_text(apps: dict[Any, sandbox.App], dumps: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for app in apps.values():
        twin = get_twin(app.product)
        assert twin is not None  # noqa: S101
        objects: list[StateObject] = twin.state_objects(dumps.get(app.id, {}))
        for o in objects:
            out[f"{app.id}:{o.key}"] = json.dumps(o.value)
    return out


def list_runs(project: Project) -> list[dict[str, Any]]:
    folder = project.state_dir / "runs"
    out: list[dict[str, Any]] = []
    if folder.is_dir():
        for path in sorted(folder.glob("r_*/result.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            out.append(
                {k: data.get(k) for k in ("run_id", "scenario", "agent", "status", "isolation")}
            )
    return out


def check_reach(plan: sandbox.Plan, agent: Agent, scen: Scenario) -> None:
    """Grants are exact (decision 0020): work that arrives somewhere the agent is not
    granted could not be read, so the run would score the scenario, not the agent."""
    spec = scen.delivery.model_dump(by_alias=True, exclude_none=True)
    product, _, op = str(spec["channel"]).partition(".")
    app = next((a for a in plan.apps if a.product == product), None)
    twin = get_twin(product)
    if app is None or twin is None:
        return  # reported by the delivery itself
    needs = twin.operations().delivery_needs.get(op)
    if needs is None:
        return
    grant = agent.grants.get(app.id)
    for key, names in needs(spec).items():
        given = (grant or {}).get(key) or {}
        missing = [n for n in names if "{{" not in n and n not in given]
        if grant is None or missing:
            what = ", ".join(missing or names)
            not_granted = (
                f"{app.id}, a system the agent file does not grant at all"
                if grant is None
                else f"{app.id}; the agent file does not grant it"
            )
            raise MirrorError(
                f"{agent.name} cannot reach the work in {scen.id}.",
                f"It arrives in {what} on {not_granted}, and grants are exact.",
                f"Grant it in agents/{agent.name}.yaml under {app.id}.{key}, "
                "or choose another scenario.",
            )


def _outside(place: str) -> bool:
    """A canary seen in an exchange through the ingress has left the world: the agent's
    platform was given it, or sent it back in a tool argument."""
    return ": from outside the world: " in place or ": sent out of the world: " in place


def agent_clients(plan: sandbox.Plan, agent: Agent, *, servers: bool = True) -> set[str]:
    """The addresses the agent's requests come from: its container, its browser, and (with
    `servers`) the MCP servers granted to it, which act for it."""
    if agent.mode == "remote":
        clients = {sandbox.REMOTE_CLIENT}  # how the ingress names the agent's platform
    else:
        clients = {agents_svc.hosted.placement(plan, agent.name).ip}
    if agent.mode == "browser":
        clients.add(agents_svc.browser.placement(plan, agent.name).ip)
    if servers:
        for app in plan.apps:
            if app.is_mcp and app.id in agent.grants:
                clients.add(app.ip)
    return clients


def grants_for(plan: sandbox.Plan, agent: Agent, org: str) -> list[access.Grant]:
    """The agent's grants, system by system, as the access map compares them."""
    out: list[access.Grant] = []
    for app in plan.apps:
        grant = agent.grants.get(app.id)
        if grant is None:
            continue
        tools = grant.get("tools")
        out.append(
            access.Grant(
                system=app.id,
                host=app.hostname,
                owner=org if grant.get("repos") is not None else "",
                repos=grant.get("repos"),
                channels=grant.get("channels"),
                tools=sorted(tools) if isinstance(tools, dict | list) else None,
            )
        )
    return out


class Reach(BaseModel):
    agent: str
    acts_as: str
    run_id: str | None = Field(description="The run set against the grants, if any")
    scenario: str | None = None
    access: dict[str, Any]


def agent_reach(project: Project, agent_name: str, run_id: str | None = None) -> Reach:
    """What the agent is granted, set against what a run used: the given run, else its
    latest run that kept an access map, else the grants alone."""
    from mirrordimensions.service import runlog

    agent, _ = agents_svc.load_agent(project, agent_name)
    world = agents_svc._world(project)  # pyright: ignore[reportPrivateUsage]
    who = agents_svc.resolve_person(world, agent)
    candidates = (
        [run_id]
        if run_id
        else [r.run_id for r in runlog.list_runs(project) if r.agent == agent_name and not r.live]
    )
    for candidate in candidates:
        result = load_result(project, candidate)
        if result.access.get("hosts") is not None:
            return Reach(
                agent=agent_name,
                acts_as=f"{who.name} ({who.username})",
                run_id=candidate,
                scenario=result.scenario,
                access=result.access,
            )
    if run_id:
        raise MirrorError(
            f"Run {run_id} kept no access map.",
            "It was recorded before access maps were kept (M6).",
            f"Run: mirror reach {agent_name}",
        )
    plan = world_plan(project)
    grants = grants_for(plan, agent, world.org)
    return Reach(
        agent=agent_name,
        acts_as=f"{who.name} ({who.username})",
        run_id=None,
        access=access.access_map([], set(), [], grants, set(plan.model_hosts)),
    )


_RUN_ID = re.compile(r"^r_[a-z0-9]{4,32}$")


class RunHandle(BaseModel):
    run_id: str
    scenario: str
    agent: str


_started: dict[str, threading.Thread] = {}


def start_run(
    project: Project, name: str, agent_name: str, *, on_step: StepFn = None, timeout: float = 120.0
) -> RunHandle:
    """Start a scenario (or a suite) in the background and return as soon as the first run
    has an id. The run is the same as `mirror run`: same steps, same result.json."""
    busy = [t for t in _started.values() if t.is_alive()]
    if busy:
        raise MirrorError(
            "A run is already in progress.",
            "Runs share one world, so they go one at a time.",
            "Wait for it to finish, or stop it.",
        )
    scenario.select(project.root / "scenarios", name)  # an unknown name fails here, not later
    agents_svc.load_agent(project, agent_name)
    first: list[str] = []
    ready = threading.Event()
    failure: list[BaseException] = []

    def started(run_id: str) -> None:
        if not first:
            first.append(run_id)
            ready.set()

    def work() -> None:
        try:
            run(project, name, agent_name, on_step=on_step, on_start=started)
        except BaseException as exc:  # noqa: BLE001 (reported to the caller, below)
            failure.append(exc)
        finally:
            ready.set()

    thread = threading.Thread(target=work, name=f"run-{name}", daemon=True)
    thread.start()
    ready.wait(timeout)
    if failure and not first:
        exc = failure[0]
        if isinstance(exc, MirrorError):
            raise exc
        raise MirrorError("The run could not start.", str(exc)[:300], "Try it with: mirror run")
    if not first:
        raise MirrorError("The run did not start in time.", "", "Try it with: mirror run")
    _started[first[0]] = thread
    # Answer once the run's first event is written, so whoever asked can read it at once.
    deadline = time.time() + 30
    folder = project.state_dir / "runs" / first[0] / "events.jsonl"
    while time.time() < deadline and not folder.is_file() and thread.is_alive():
        time.sleep(0.1)
    return RunHandle(run_id=first[0], scenario=name, agent=agent_name)


def stop_run(project: Project, run_id: str) -> None:
    """Ask a run in progress to end; it is scored and marked `stopped`."""
    from mirrordimensions.service import runlog

    folder = run_dir(project, run_id)
    if (folder / "result.json").is_file():
        raise MirrorError(f"Run {run_id} has already ended.", "", "")
    if runlog.current_run(project) != folder.name:
        raise MirrorError(
            f"Run {run_id} is not in progress.",
            "It has no result, and no mirror process is running it: it did not finish.",
            "Its events are still readable: mirror trace " + folder.name,
        )
    write_text(folder / STOP_FILE, "stop\n")


def run_dir(project: Project, run_id: str) -> Path:
    """The folder of an existing run. `latest` names the most recent one."""
    folder = project.state_dir / "runs"
    if run_id == "latest":
        runs = sorted(
            (p for p in folder.glob("r_*") if (p / "events.jsonl").is_file()),
            key=lambda p: (p / "events.jsonl").stat().st_mtime,
        )
        if not runs:
            raise MirrorError(
                "There are no runs yet.", "", "Run: mirror run <scenario> --agent <name>"
            )
        return runs[-1]
    if not _RUN_ID.match(run_id):
        raise MirrorError(
            f"{run_id!r} is not a run id.",
            "Run ids look like r_8f3k2a91c0.",
            "List them with: mirror runs",
        )
    path = folder / run_id
    if not (path / "events.jsonl").is_file():
        raise MirrorError(f"There is no run {run_id}.", "", "List them with: mirror runs")
    return path


def write_report(project: Project, run_id: str) -> Path:
    """Rebuild a run's report.html from its folder."""
    return report.write(run_dir(project, run_id))


def load_result(project: Project, run_id: str) -> Result:
    path: Path = run_dir(project, run_id) / "result.json"
    if not path.is_file():
        raise MirrorError(
            f"Run {run_id} has no result.",
            "It is still running, or stopped before it was scored.",
            f"Follow it with: mirror trace {run_id} --follow",
        )
    return Result.model_validate_json(path.read_text(encoding="utf-8"))
