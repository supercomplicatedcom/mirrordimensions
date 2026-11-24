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
import secrets
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from mirrordimensions.config.agent import Agent
from mirrordimensions.config.result import Result, WorldRef
from mirrordimensions.config.scenario import Scenario
from mirrordimensions.engine.registry import get_engine
from mirrordimensions.errors import MirrorError
from mirrordimensions.hostos.files import make_dir, write_text
from mirrordimensions.network import sandbox
from mirrordimensions.network.events import Collector, tracer_parser
from mirrordimensions.project import Project
from mirrordimensions.runner import coverage, evaluate, ledger, scenario
from mirrordimensions.service import agents as agents_svc
from mirrordimensions.service import results
from mirrordimensions.service import world as world_svc
from mirrordimensions.service.sandbox import (
    _docker,  # pyright: ignore[reportPrivateUsage]
    _manifest,  # pyright: ignore[reportPrivateUsage]
    app_secrets,
    world_plan,
)
from mirrordimensions.service.worlddef import definition_hash
from mirrordimensions.twins.base import RunContext, StateObject, get_twin
from mirrordimensions.twins.relay import Relay
from mirrordimensions.world.model import Person, World

IDLE_S = 30.0  # no traffic from the agent for this long: it has finished
POLL_S = 2.0
BODIES = "/home/mitmproxy/spool"  # the gateway's body store
StepFn = Callable[[str], None] | None


class RunOutcome(BaseModel):
    run_id: str
    scenario: str
    status: str
    isolation: str
    coverage: str
    path: str


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
) -> list[RunOutcome]:
    chosen = scenario.select(project.root / "scenarios", name)
    agent, _ = agents_svc.load_agent(project, agent_name)
    if agent.status == "draft":
        raise MirrorError(
            f"{agent_name} is still a draft.",
            "Its onboarding is not finished.",
            f"Run: mirror agent new --resume {agent_name}",
        )
    outcomes: list[RunOutcome] = []
    for item in chosen:
        outcome = _Run(project, item, agent, allow_emulated, max_minutes, on_step).execute()
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
        self._platform(driver, boundary)
        self.collector.emit(
            "runner",
            "run.start",
            {
                "scenario": self.scenario.id,
                "agent": self.agent.name,
                "acts_as": self.person.username,
            },
        )
        handle = None
        stopped, errored = False, False
        try:
            if not self._isolation():
                return self._finish(stopped=False, errored=False)
            seconds = world_svc.restore(self.project, docker, self.plan)
            self.collector.emit(
                "runner", "snapshot.restored", {"snapshot": "base", "seconds": seconds}
            )
            self.step(f"Restored the base snapshot in {seconds}s")
            self._overlay()
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
            stopped = ended == "timeout"
            if stopped:
                self.result.reason = f"stopped at max_minutes ({int(self.max_s // 60)})"
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

    def _platform(self, driver: str, boundary: str) -> None:
        status = get_engine().status()
        p = self.result.platform
        p.engine_driver = driver if driver in ("lima", "wsl", "host") else None  # pyright: ignore[reportAttributeAccessIssue]
        p.engine_arch = (
            "arm64" if status.arch == "arm64" else ("x64" if status.arch == "x64" else None)
        )
        p.boundary = boundary if boundary in ("dedicated-vm", "shared-vm", "host") else None  # pyright: ignore[reportAttributeAccessIssue]
        p.docker_version = status.versions.get("docker")
        p.runsc_version = status.versions.get("runsc")
        p.guest_kernel = status.versions.get("kernel")
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
        product, _, op = name.partition(".")
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
        where = agents_svc.hosted.placement(self.plan, self.agent.name)
        clients = {where.ip}
        if self.agent.mode == "browser":
            clients.add(agents_svc.browser.placement(self.plan, self.agent.name).ip)
        for app in self.plan.apps:
            if app.is_mcp and app.id in self.agent.grants:
                clients.add(app.ip)  # the MCP server acts for the agent
        return clients

    def _wait(self, handle: agents_svc.AgentHandle, started: float) -> str:
        done_when = self.scenario.limits.done_when
        deadline = started + self.max_s
        last_activity, seen = started, 0
        while time.time() < deadline:
            if not self.docker.is_running(handle.where.name):
                return "exited"
            mine = [
                e
                for e in self.collector.events
                if e.get("type") in ("http.exchange", "dns.query", "browser.action")
                and (e["data"].get("client") in handle.clients)
            ]
            if len(mine) != seen:
                seen, last_activity = len(mine), time.time()
            if done_when != "process_exit" and seen and time.time() - last_activity > IDLE_S:
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

    def _bodies(self, clients: set[str]) -> list[tuple[int, str, str]]:
        """(event seq, where, text) for every request body the agent sent, and model answers."""
        out: list[tuple[int, str, str]] = []
        for e in self.collector.events:
            data = e.get("data", {})
            if e.get("type") != "http.exchange" or data.get("client") not in clients:
                continue
            where = (
                f"{data.get('method')} {data.get('host')}{str(data.get('path', '')).split('?')[0]}"
            )
            for ref in (data.get("req_body_ref"),):
                if ref:
                    raw = self.docker.read_file(sandbox.GATEWAY_NAME, f"{BODIES}/{ref}")
                    if raw:
                        out.append((int(e["seq"]), where, raw.decode("utf-8", "replace")))
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
            product, _, op = name.partition(".")
            twin = get_twin(product)
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
            app = apps[name.split(".")[0]]
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
        travel = evaluate.canary_travel(canary_values, bodies, final, planted)
        self.result.canaries = [{"canary": t.name, "seen": t.places} for t in travel]

        self.result.egress = evaluate.egress(
            self.collector.events, handle_clients, set(self.plan.resolvable)
        )
        writes = [(seq, text) for seq, where, text in bodies if not where.startswith("GET ")]
        flags = evaluate.suspicions(writes)
        for flag in flags:
            self.collector.emit("evaluator", "suspicion.flag", flag)
        self.result.suspicion = flags
        self.result.suspected = bool(flags)
        self._ledger(handle_clients)
        self._coverage(handle_clients, found)

    def _body(self, ref: str | None) -> bytes:
        if not ref:
            return b""
        return self.docker.read_file(sandbox.GATEWAY_NAME, f"{BODIES}/{ref}") or b""

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
        connections = coverage.reconcile_connections(
            sockets,
            gateway=self.plan.addr.gw_lan,
            resolver=self.plan.addr.dns_ip,
            refused=refused,
            exchanges=exchanges,
            lookups=lookups,
        )
        recs = {
            "state_against_requests": coverage.reconcile_state(found, writes),
            "connections_against_captures": connections,
            "processes_against_image": coverage.reconcile_processes(
                execs, sockets, connections["passed"]
            ),
        }
        mcp_apps = [a for a in self.plan.apps if a.is_mcp and a.id in self.agent.grants]
        if mcp_apps:
            from mirrordimensions.mcp.world import reconcile as mcp_reconcile

            fronts = {a.ip for a in mcp_apps}
            problems = mcp_reconcile.reconcile(events, {a.hostname for a in mcp_apps}, fronts)
            problems += mcp_reconcile.unexplained_writes(events, fronts)
            calls = sum(1 for e in events if e.get("type") == "mcp.call")
            recs["mcp_calls_against_writes"] = {
                "passed": not problems,
                "detail": f"{calls} tool call(s); every write through MCP explained by its call, and every write call by a write",
                "unexplained": problems,
            }
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
        self.step(f"{self.scenario.id}: {self.result.status}")
        return RunOutcome(
            run_id=self.run_id,
            scenario=self.scenario.id,
            status=self.result.status,
            isolation=self.result.isolation,
            coverage=str(self.result.coverage.get("status", "complete")),
            path=str(self.dir),
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


def load_result(project: Project, run_id: str) -> Result:
    path: Path = project.state_dir / "runs" / run_id / "result.json"
    if not path.is_file():
        raise MirrorError(f"There is no run {run_id}.", "", "Run: mirror runs")
    return Result.model_validate_json(path.read_text(encoding="utf-8"))
