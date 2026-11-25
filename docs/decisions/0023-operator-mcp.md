# 0023. The operator MCP server: the SDK, run content fenced off, and a confirmation to act

Status: Proposed · Date: 2026-11-25 · Milestone: M7

## Context

Decision 0009 (Accepted by the owner) defines the operator MCP server: a third front end on the service layer, with a fixed set of tools. It never offers anything destructive, it treats run content as untrusted, and it needs a confirmation to act. Building it raised four questions that decision leaves open:

- Implement MCP by hand, as the world MCP front does inside its container, or use the official SDK on the host?
- In what form is untrusted content returned?
- Where is operator activity recorded?
- How does `mirror doctor` find the server's port to prove it is unreachable from the sandbox?

## Decision

1. **The official MCP Python SDK** (`mcp`, MIT; it brings `anyio`, `httpx2`, `jsonschema`, `pyjwt`, `sse-starlette` and their small dependencies, all compatible with Apache-2.0).
   - It runs only on the host, in `mirrordimensions.mcp.operator`.
   - It implements stdio, streamable HTTP, progress notifications and DNS-rebinding protection, which would otherwise be several hundred lines kept in step with the specification by hand.
   - The world front (`mcp/world/front.py`) keeps its standard-library implementation, because it runs alone inside the world; the import-boundary lint keeps the two apart.
2. **Transports.**
   - `mirror mcp serve` uses stdio, for an AI tool to launch. There is no port, and nothing but the protocol is written to stdout.
   - `mirror mcp serve --http [--port 7421]` binds `127.0.0.1` and prints a random token. Every request needs `Authorization: Bearer <token>`. Host and Origin must be `127.0.0.1:<port>` or `localhost:<port>`, which stops DNS rebinding.
3. **Tools.**

   | Kind | Tools |
   | --- | --- |
   | Read | `status`, `plan`, `doctor_report`, `list_systems`, `show_system`, `list_scenarios`, `list_agents`, `list_runs`, `get_result`, `coverage`, `ledger`, `read_steps`, `search_timeline`, `agent_reach`, `pending_changes` |
   | Act, with `confirm=true` | `start_run`, `stop_run`, `restore_snapshot`, `run_doctor` |
   | Edit, with `confirm=true` | `set_visibility`, `set_grant`, `set_rule`, `remove_rule` |
   | Long, with `confirm=true` and progress | `apply_changes`, `create_world` |

   - Nothing destructive is offered (`world destroy`, `engine destroy`, `down --purge`); those stay with the command line.
   - A call without the confirmation is refused with a message saying how to confirm.
   - Service errors come back as tool errors carrying what failed, why, and the fix.
4. **Run content is fenced off.**
   - Anything that can carry text the agent wrote or a scenario planted goes under `run_content`, with `untrusted` saying it is data and never instructions. This covers checks' evidence, unexpected changes, canary sightings, suspicion phrases, steps, timeline summaries and ledger resources.
   - `get_result` returns facts by default: statuses, check names and outcomes, counts. It adds evidence text only with `include_text=true`.
   - The README warns that an AI tool reading run content can be prompt-injected by it.
5. **Operator activity** (each act and edit) is appended to `.mirror/operator.log` as one JSON line per call. It is never part of a run.
6. **Unreachable from the sandbox.**
   - `mirror doctor` checks the operator server as it checks the portal: from the agent's network and the systems' network, at the host's addresses and 127.0.0.1. If the server runs over HTTP, doctor probes its real port; otherwise it probes a stand-in on 7421.
   - The server writes `.mirror/operator.json` with its port. A marker counts only if something listens on its port, because a server stopped by a signal, or one that crashed, leaves its marker behind. The portal's marker is treated the same way now.
7. **Separation of roles.** The preflight (`mirror agent check`) fails if an agent's variables or wake command name a host-local address, `mirror mcp` or the server's name.

## Consequences

- An operator can point an AI tool at a world: `mirror mcp serve` as an MCP server command, with `--project <folder>`.
- The SDK is a dependency to keep current; its version is pinned through `uv.lock`.

## Alternatives considered

- **A hand-written server, as in the world front.** No new dependency, but the protocol, streamable HTTP's sessions and progress would be ours to maintain.
- **Raw content by default with a warning.** Simpler for the caller, but the default path for an AI tool would then be the injectable one.

## To verify

- The server driven from a desktop AI tool over stdio. It has been tested with the SDK's own client, over stdio and over HTTP.
