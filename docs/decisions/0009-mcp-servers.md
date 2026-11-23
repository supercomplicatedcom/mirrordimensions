# 0009. Two MCP servers: one inside the world for agents, one outside it for operators

Status: Accepted (owner) for building both; the rest Proposed · Date: 2026-11-23 · Milestones: M4, M5, M7, M7.5, M8

## Context

Company agents increasingly reach company systems through MCP servers rather than raw APIs or a browser, and many of those agents run on a vendor's cloud (an assistant platform, an agent builder), not in a container the company controls. A world that cannot serve MCP cannot test them. Separately, operators and their own AI tools (Claude Code, a company's automation) want to drive MirrorDimensions itself: create worlds, start runs, read results.

These are two different servers with opposite rules. The first is part of the world and must be indistinguishable from the company's real MCP servers. The second is control-plane machinery and must be invisible from inside any world.

## Decision

**1. Two servers, never shared.** They share no process, port, hostname, credential or code path beyond the service layer's data models.

| | World MCP server | Operator MCP server |
| --- | --- | --- |
| Who calls it | The agent under test | An operator, or an operator's AI tool |
| Where it lives | Inside the world, on the system network behind the gateway, like a twin | On the host (local) or in the cloud service's control plane |
| What it exposes | The company's tools, backed by the twins | MirrorDimensions' own service layer |
| Must look like | The company's production MCP servers | Nothing in particular: it is never seen by an agent under test |
| Captured | Every message, as a coverage channel | Logged as operator activity, not as run evidence |
| Milestone | M4 (inside the sandbox), M7.5 (remote agents) | M7 |

**2. The world MCP server.**

- **It is a system in the world.** An entry in `apps:` with `kind: mcp-server`, its own production-style hostname, and a profile. The MCP front is a small service built from this repository at build time and run on the system network. It holds only the tool definitions and the routes to twins: no world file, scenario, check or canary list. It reaches twins over the system network, as the gateway does.
- **Same tools as production.** Tool names, descriptions, input schemas, the server's reported name and version, protocol version and any instructions text come from one of three places:
  - an exported tool list the admin supplies;
  - the import of the agent's MCP configuration (M8);
  - for well-known public MCP servers, a catalog specification.

  Nothing is fetched from a real server: that would be pointing code at a real organization's systems.
- **Tools map to surfaces.** Each tool is declared in the profile like an endpoint: which twin operation it calls, its resource pattern, access (read or write), a sentence for the live view, and what it exposes. `locate`, `describe` and `exposed` therefore work for MCP calls, and behavior rules (latency, errors, `insert_text` for planted instructions) apply to tool results as they do to HTTP responses.
- **Transports.**
  - Streamable HTTP through the gateway, with TLS from the install's CA, at the hostname the agent's configuration already uses.
  - Production MCP hostnames that belong to a vendor (a hosted MCP endpoint) resolve to the gateway like model hosts do, and are routed to the world MCP front.
  - stdio MCP servers packaged inside the agent's own image are part of the agent. Their outbound API calls go through the gateway like any other traffic, so the world must answer the APIs they call.
- **Identity.** Credentials are issued in production form, as a bearer token or through the product's OAuth flow, by the same identity step that issues twin accounts. The grants are the agent's grants: an out-of-grant tool call gets the production server's own error.
- **Capture and coverage.** A new coverage channel, `mcp`. Every JSON-RPC message, requests, responses and notifications streamed over SSE alike, becomes an `mcp.message` event, linked to the HTTP exchange that carried it. Each tool call becomes an `mcp.call` event with tool name, arguments (redacted), result and the resources it located and exposed. The reconciliation "state against requests" counts writes made through MCP tools. Done means captured, listed in coverage, and covered by a reconciliation test (CLAUDE.md).
- **Tells to close.** Server info, error shapes, pagination cursors, capability lists and timing must match the production server's. Each difference found goes in `docs/tells.md`.

**3. Remote agents (M7.5).**

For agents that run on a vendor's platform and cannot be put in a container. This replaces the earlier "remote gateway through an authenticated tunnel", which was designed but not built.

- **An ingress** exposes one world's MCP endpoints to the internet. It is a separate component on its own network, which reaches only the world MCP front: never a twin directly, never the agent network, never the control plane. The ingress terminates TLS with a publicly trusted certificate for a hostname the customer controls (for example a subdomain they delegate). It never uses `mirrordimensions.com` or any name that reveals the product.
- **Authorization** follows the MCP specification for remote servers (OAuth 2.1, with the agent platform registering as a client), issued for the synthetic person the agent acts as.
- **Self-hosted and cloud.** The open project includes the ingress and its configuration, so a self-hosting team can expose a world through their own reverse proxy or load balancer. `mirror` never starts a third-party tunnel by itself. The cloud service sells the managed version: hosted ingress, certificates and a stable endpoint per world. This follows the project's boundary rule: everything a self-hosting team needs for a trustworthy result is open, so a self-hosting team can get a trustworthy result without the cloud.
- **Weaker guarantees, stated plainly.**
  - The agent keeps its own internet access, so a leak is detected (canaries seen leaving through tool arguments or arriving elsewhere) but cannot be blocked.
  - Its model calls happen on the vendor's side and are not captured.
  - Hostnames differ from production unless the customer delegates their real ones.

  Remote runs report isolation `remote` and boundary `remote`. Coverage lists the uncaptured channels (`model`, `agent_host`) as `not_captured` with the reason `agent runs outside the world`. A remote result is evidence about what the agent did to the world, never about what it did elsewhere, and its report says so on the first screen. It does not exit with code 4 for those two channels alone, but every other channel must be `captured`.
- **Onboarding.** The "Remote gateway" column of the onboarding flow is built in M7.5, with the reduced-guarantee notice shown and accepted.

**4. The operator MCP server.**

- **A third front end** on `mirrordimensions.service`, next to the CLI and the portal, with no logic of its own.
- **Tools:**
  - **Read:** project and world status, plan, doctor report, list systems, scenarios, agents and runs, get result, read steps, search the timeline, coverage and ledger.
  - **Act:** start and stop a run, restore a snapshot.
  - **Edit, as pending changes:** set a rule, a visibility or a grant.
  - **Long operations stream progress:** build and world creation.
  - **Never exposed:** destructive commands (`world destroy`, `engine destroy`, `down --purge`, `snapshot rm`). They stay with the CLI.
- **Transport.**
  - Locally, `mirror mcp serve` runs over stdio, launched by the operator's tool, so there is no network port at all.
  - `mirror mcp serve --http` binds to `127.0.0.1` with a random token, like the portal.
  - In the cloud service it is authenticated per organization and user (through the `Authenticator` plug-in point).
- **Hidden machinery.** It is a control-plane interface. It must never be reachable from any engine network. The egress and inside-out suites test it exactly as they test the portal.
- **Run content is untrusted.** Results and timelines contain text written by the agent under test and by injection scenarios, which is deliberately hostile. Every tool result that carries such content marks it as untrusted data. Tools return structured facts by default and quote raw content only on request. Write and act tools require an explicit confirmation argument. The docs warn operators that an AI tool reading run content can be prompt-injected by it.
- **Separation of roles.** An agent registered to be tested must not also hold operator MCP credentials. `mirror agent check` fails if an agent's configuration or environment references the operator MCP server.

**5. Where the code lives.**

```
src/mirrordimensions/mcp/
  world/      # the MCP front built into the world's image; tool mapping from profiles
  ingress/    # remote exposure (M7.5)
  operator/   # the operator server over the service layer
```

Nothing under `mcp/world/` may import from `mcp/operator/` or the service layer. A lint check enforces it.

## Consequences

- MCP becomes a first-class way into the world, alongside API and browser, so the scenarios gain MCP variants: the same work and checks, delivered to an agent that only has MCP tools.
- The world MCP front is the first agent-reachable service built from this repository's own code, not upstream software. It must meet the same bar as a twin: no tells, no reach into the control plane. It is reviewed like one.
- Remote runs make a new kind of result with an explicit, smaller claim. The report and the portal must never present it as if it were `full`.
- Operators get a scriptable, AI-friendly interface without any new path into a world.

## Alternatives considered

- **One MCP server for both.** Rejected: it would put control-plane machinery where the agent can find it.
- **Only raw APIs, with agents expected to bring their own MCP servers.** Rejected: vendor-hosted agents call remote MCP endpoints and can bring nothing.
- **Fetching tool lists from the company's real MCP servers.** Rejected: it touches real systems. Tool lists come from exports, imports or the catalog.
- **A third-party tunnel started automatically for remote agents.** Rejected: it would route the world through a service outside the operator's control.

## To verify

- The current MCP specification: Streamable HTTP transport, session handling, authorization (OAuth 2.1 and client registration), and the protocol version to target. Check it again when M4 and M7.5 start.
- The official MCP Python SDK's server support for Streamable HTTP and stdio, for both servers.
- How major agent platforms connect to remote MCP servers (authorization flow, required hostnames, allow-listing), before M7.5.
