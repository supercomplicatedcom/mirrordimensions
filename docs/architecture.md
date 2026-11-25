# Architecture

MirrorDimensions builds a synthetic company, runs an AI agent inside it, records everything the agent touches, and scores the run. This page explains how the parts fit together. The reasons behind each choice are in [decisions/](decisions/); what has been measured on each host is in [platforms.md](platforms.md).

## Three places

```
 host (macOS, Linux, Windows)            engine (a Linux VM the mirror manages)
 ┌───────────────────────────┐           ┌──────────────────────────────────────────────┐
 │ mirror (the control plane)│  Docker   │  sandbox, one per project                    │
 │  - project files          │   API     │  ┌────────────┐   ┌──────────────────────┐   │
 │  - world generator        │ ────────▶ │  │ agent      │──▶│ gateway   resolver   │   │
 │  - runner and evaluator   │  only     │  │ (gVisor or │   │ (TLS, capture,       │   │
 │  - .mirror/ run records   │           │  │  microVM)  │   │  rules)  (DNS)       │   │
 │                           │           │  └────────────┘   └──────────┬───────────┘   │
 └───────────────────────────┘           │                         systems (twins)      │
                                         │                         Gitea, Mattermost…   │
                                         │  engine firewall: only the model endpoint    │
                                         │  leaves; every other packet is dropped and   │
                                         │  logged                                      │
                                         └──────────────────────────────────────────────┘
```

- **The host** runs `mirror`, the control plane, and, when asked, the portal (`mirror portal`): a web page on `127.0.0.1` over the same service layer, never on any sandbox network (decision 0017). It holds the project (`mirror.yaml`, agents, scenarios, the root CA) and every run's record under `.mirror/`. Nothing on the host is shared with the engine: no folders, no ports, no route back (decisions 0002 to 0004).
- **The engine** is a Linux VM the mirror creates and owns: Lima on macOS and Linux, WSL on Windows (experimental). The control plane reaches it only through its Docker API, on a socket only the owner can open. Containers run as hardened ordinary containers in the engine, with gVisor as an option, or, on hosts with nested virtualization, in Firecracker microVMs (decisions 0010 and 0012). The engine installs updates only when asked (`mirror engine update`), so a run never meets a restarted Docker or a kernel nobody chose (decision 0019).
- **The sandbox** is one project's world inside the engine: the agent, the systems it works in, and the infrastructure that makes them look real and records what happens. The agent sees a company network with production-style hostnames and valid TLS. Nothing in it names the mirror, a test or a sandbox ([tells.md](tells.md) lists every giveaway found and how it was closed).
- **The ingress** (only while a world is exposed to a remote agent) is one more container on its own internal network, whose only other member is the exposed MCP server. It listens on its own loopback; `mirror world expose` relays connections into it from the host's 127.0.0.1 through the Docker API, behind the team's reverse proxy, which holds the public certificate. It records every exchange and MCP message as the gateway does (decision 0024).

## Inside the sandbox

| Role | Container | What it does |
| --- | --- | --- |
| Resolver | `ns1`, `ns2` | Answers only the world's names; logs every query and answer |
| Gateway | `edge-proxy-02` | Terminates TLS with the world's CA; forwards to the systems; records every exchange with bodies; applies rules; puts the real model key in place of the agent's placeholder |
| Systems | `app-NN`, `db-NN` | The twins: real open-source products (Gitea, Mattermost), configured, never modified (decision 0011) |
| MCP servers | `app-NN` | The company's own tool servers, when an agent is given tools (decision 0009) |
| Control relay | `ops-01` | How the control plane calls a system's API (setup, scenario steps, checks, state dumps): on the systems' network only, never the agent's |
| Kernel log relay | `klog` | Brings the engine firewall's drop log out through the Docker API |
| Tracer | `auditd-01` | Tetragon in the engine kernel: every process the agent starts and every socket it opens (decision 0016) |
| Browser desk | per run | For browser agents: Chromium and an observer that records every DevTools command, navigation and screenshot (decision 0014) |

The agent's container joins the company network only. Its one way out is the gateway; the engine firewall drops anything else and logs it. The model endpoint is reached through the gateway too, so every call is recorded (decision 0013).

## A run

`mirror run <scenario> --agent <name>` does this, in order (decision 0015):

1. Check isolation, then restore the world to its base snapshot (`snapshot.restored`).
2. Apply the scenario's overlay: commits, issues, planted files and tokens (`overlay.applied`).
3. Deliver the work as a colleague would: an assigned issue, a chat message, a direct message (`work.delivered`).
4. Start the agent with credentials in the form the company would issue them (`agent.woken`).
5. Record everything while the agent works.
6. When the agent stops (it exits, goes idle, or reaches its time limit), dump every system's state and compare it with the state before (`state.diff`).
7. Score: success checks, forbidden checks, unexpected side effects, where each canary value travelled, attempts to leave the world, and the suspicion scan (`check.result`, `side_effect.unexpected`, `suspicion.flag`).
8. Reconcile the records against each other to prove coverage is complete (below).
9. Write `result.json` and `report.html` (`run.end`).

## Events

Every source writes into one file, `.mirror/runs/<run-id>/events.jsonl`, one JSON object per line, as the events arrive on the host. Each has a sequence number, a timestamp (host time corrected by the engine's clock offset), a source, a type and its data. `mirror trace` reads it back as one ordered timeline; results and reports refer to events by their sequence number.

| Source | Types | Recorded by |
| --- | --- | --- |
| `runner` | `run.start`, `snapshot.restored`, `overlay.applied`, `work.delivered`, `agent.woken`, `run.end` | the control plane |
| `gateway` | `http.exchange`, `ws.frame`, `route.unknown_host`, `rule.applied`, `tls.handshake` | the gateway; bodies are stored, credentials redacted |
| `model` | `model.exchange` (one per call, naming the HTTP exchange that carries it), `model.refused`, `model.hosted_tools` | the gateway, on model routes |
| `mcp` | `mcp.message` (every JSON-RPC message), `mcp.call` (tool, arguments, result, resources) | the gateway, on MCP servers |
| `dns` | `dns.query` | the resolver |
| `egress` | `egress.blocked` | the engine firewall, through the kernel log relay |
| `browser` | `browser.navigate`, `browser.action`, `browser.screenshot`, `browser.connect`, `browser.disconnect`, `browser.target`, `browser.observer_ready`, `browser.observer_error` | the browser observer |
| `host` | `process.exec`, `socket.connect` | the tracer |
| `state` | `state.diff` | the control plane, from state dumps |
| `evaluator` | `check.result`, `side_effect.unexpected`, `suspicion.flag` | the evaluator |

The schema is in `src/mirrordimensions/config/events.py`; `mirror schema event` prints it.

Each `http.exchange` to a system with a profile also carries `where`: the surface it matched, the resource it acted on, and a plain sentence ("Posts in #incidents"). The gateway records it as it captures the exchange, from the same profile code the host uses, so a run reads the same live and in replay. `run.start` names the agent's addresses (`clients`).

## Editing

Edits are written to `mirror.yaml` or the agent's file at once (decision 0021). Rules, visibility between granted, denied and present, and grants take effect at the next run: each run hands the gateway its current routes, and the gateway reloads them, so nothing has to be restarted. A system made absent or brought back restarts the sandbox. Its settings, the company and its data change what is built, so they wait for a rebuild. `mirror changes` lists what is saved but not yet in effect, measured against `.mirror/built.json` and `.mirror/applied.json`; `mirror apply` puts it into effect now.

## Steps and the live view

`trace/steps.py` groups a run's events into steps for the portal's live view and `mirror watch` (decision 0018):

- Requests to one resource within two seconds become one step. A change is never merged into the reads before it.
- A model call is a `think` step. Refused requests, failed lookups and blocked connections are `blocked` steps.
- When a forbidden check fails, the step holding the request it names becomes a `violation`.

Steps are sent as soon as they open and again, with the same index, as they grow, so the live view shows each step a fraction of a second after the event that caused it. A finished run replays from the same steps.

## Coverage

A run is trusted only if everything the agent could do was recorded. Each run's `result.json` has a `coverage` block listing every channel (HTTP, WebSocket, DNS, egress, model, browser, MCP, host, state) as captured or not applicable, and three reconciliations that check the records against each other:

- **State against requests.** Every object that changed in a system is explained by a write the gateway recorded.
- **Connections against captures.** Every connection the tracer saw from the agent went to the gateway, the resolver or its browser and was recorded there, or was refused and logged by the firewall.
- **Processes against image.** The programs the agent ran, and which of them opened sockets.

If any of these fails, coverage is `incomplete` and the run exits with code 4, whatever its checks say.

A remote agent's run (decision 0024) covers only what the agent did to the world. Its model and its host are outside, listed as `model` and `agent_host` not captured; those two alone do not make coverage incomplete, and the report says so on its first screen. Its reconciliations are state against requests, MCP calls against writes, and every exchange from its platform having come through the ingress. A canary its platform was given, or sent back in a tool argument, is reported as having left the world.

## A run's folder

| File | What it holds |
| --- | --- |
| `events.jsonl` | The timeline, every source |
| `result.json` | Status, checks with evidence, side effects, canary travel, egress attempts, suspicion flags, the access map, coverage, the world's seed and the platform |
| `ledger.json` | Every resource the agent touched, how, and whether its model saw it |
| `report.html` | One self-contained page: open it offline, share it as a file |
| `model/` | Each model call's prompt and answer, credentials redacted |
| `screens/` | Browser screenshots |
| `agent.log` | What the agent printed |

## The code

| Package | Holds |
| --- | --- |
| `cli/` | The `mirror` command: argument parsing and output only |
| `portal/` | The local portal: `server.py` (the HTTP API over `service/`) and `web/` (the React front end, built into `static/`) |
| `mcp/operator/` | The operator MCP server (`mirror mcp serve`): the service layer as MCP tools for an operator's AI tool, on the host only (decisions 0009, 0023) |
| `service/` | What each command does: drives the engine and calls the pure packages |
| `config/` | The file formats (manifest, agent, scenario, event, result) as typed models |
| `engine/` | Creating and checking the engine on each host. The only place, with `hostos/`, that knows which OS it runs on |
| `hostos/` | Portable file permissions, locks, directories and sleep detection |
| `network/` | The sandbox plan, certificates, DNS and the collector; `payloads/` holds the code copied into sandbox containers |
| `world/` | The deterministic company generator |
| `twins/` | One folder per product. Nothing outside `twins/` names a product ([writing a twin adapter](writing-a-twin-adapter.md)) |
| `runner/` | Scenarios, evaluation, the ledger, coverage and the suspicion phrases |
| `trace/` | The timeline, `mirror trace` lines, the access map and the report |
| `agents/` | Starting hosted and browser agents |
| `mcp/world/` | The world MCP front, built into the world: standard library only, never importing the service layer or the operator server |
| `snapshot/` | Saving and restoring the world's volumes |
| `scenarios/core/` | The built-in scenarios ([writing a scenario](writing-a-scenario.md)) |
