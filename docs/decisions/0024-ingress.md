# 0024. The ingress for remote agents: a relay through the Docker API, TLS at your proxy, sign-in as the person

Status: Accepted (owner), points 1 to 3; points 4 to 9 Proposed · Date: 2026-11-25 · Milestone: M7.5

## Context

M7.5 lets an agent that runs on a vendor's platform work in a world through its MCP server (decision 0009, point 3). This is the first time anything outside reaches into a world. Three things were not settled:

- **How traffic gets in.** The engine forwards nothing to the host but the Docker socket (decision 0004).
- **Who holds the public certificate.** Decision 0009 says the ingress terminates TLS with a publicly trusted certificate for a hostname the customer controls.
- **Who signs in.** The OAuth flow the MCP specification requires sends someone to a sign-in page, and nothing said whose.

## Decision

1. **A relay through the Docker API** (the owner's choice, 2026-11-25, over adding one engine port forward).
   - `mirror world expose` runs a process on the host that listens on 127.0.0.1.
   - It carries each connection into the ingress container through a Docker exec stream: no terminal, with Docker's output frames unpacked, byte for byte. That costs about 40 ms per connection, measured.
   - The engine keeps its single forward, the Docker socket, and decision 0004 is unchanged.
   - The ingress listens only on its own loopback, so nothing on any engine network, the ingress network included, can open a connection to it.
2. **TLS ends at the owner's reverse proxy** (the owner's choice, over the ingress holding the certificate).
   - The proxy holds the certificate for the public hostname, as it does for the team's other services, and forwards plain HTTP to the relay on 127.0.0.1.
   - `mirror world expose` prints the proxy settings (Caddy and nginx).
   - This replaces decision 0009's wording that the ingress itself terminates TLS. The mirror never holds the certificate's private key.
3. **The person the agent acts as signs in** (the owner's choice, over a one-time code).
   - The world MCP front serves OAuth 2.1 as the MCP specification requires for remote servers: protected-resource metadata, authorization-server metadata, dynamic client registration, authorization code with PKCE (S256), and refresh.
   - Its sign-in page, in the company's name, takes the synthetic person's username and password, which `expose` prints for the owner to type. The access token is the person's MCP token, with the agent's exact grants.
4. **The ingress reaches only the MCP front.**
   - The ingress container sits on its own internal network (`10.43.0.0/24`), with the exposed MCP front as its only other member. It reaches no twin, database, resolver, gateway or agent-network address, and has no route out.
   - It runs the gateway's own capture code (`edge.py`) with one route, the public hostname to the front, so every exchange and MCP message through it is recorded as the gateway records them.
   - A check run from the ingress network proves the rest unreachable.
5. **No forbidden names.** The public hostname must pass the naming lint, which includes `mirrordimensions.com`. So must the sign-in page and every OAuth and MCP response.
6. **A remote run waits for the platform.** `mirror run <scenario> --agent <remote agent>` restores the world, applies the overlay and delivers the work as for any agent. It then waits while the agent works from its platform, and ends when the agent has made no request through the ingress for 30 seconds, the scenario's end condition is met, the operator stops it, or the time limit is reached. It refuses to start unless an MCP server the agent is granted is exposed and the ingress is running for this world.
   - The ingress names every client `remote`: its only traffic is the agent's platform's, arriving through the relay. Its events are marked `via: ingress` and numbered apart from the gateway's.
7. **What a remote result covers.** Isolation and boundary are `remote`. Coverage lists `model` and `agent_host` as `not_captured` ("agent runs outside the world"); those two alone do not make coverage incomplete (exit code 4). DNS, egress and the browser are not applicable; HTTP, MCP and state must be captured. The reconciliations are state against requests, MCP calls against writes (on the MCP endpoint only: the server also serves sign-in), and a check that every exchange from the platform came through the ingress. The report's first screen says the result covers only what the agent did to the world.
8. **Canaries that reach the platform have left the world.** A canary in a response sent through the ingress (`sent out of the world`), or in a tool argument arriving through it (`from outside the world`), is reported with `left_world: true`. Response bodies count only for canary travel, never for forbidden checks: reading a file is not posting it.

9. **Onboarding's remote column.** `mirror agent new --mode remote` and the portal's "Remote gateway" show the same notice (`REMOTE_NOTICE`): leaks are detected, not blocked; the agent's model and platform are outside the record; the public hostname may differ from production. Onboarding goes on only once it is accepted, which the agent file records as `reduced_guarantees: accepted`; a remote agent file without it is invalid.
   - The model is the vendor's own (no route), and work arrives through the vendor's own trigger (no wake). The role's usual access includes every tool of the world's MCP servers, and at least one must be granted.
   - The preflight checks that an MCP server it is granted is exposed, the ingress runs for this world, its person can sign in, and nothing the platform is shown names a test. It reports whether the relay is listening, and reports coverage as partial.

## Consequences

- Exposing a world means running `mirror world expose` beside a reverse proxy the team already operates. Nothing is exposed while it is not running.
- A world can be reached only by the agent and person it was exposed for: the sign-in page accepts that person alone.
- A careful agent's remote run still reports the scenario's canary as having left the world when it reads the file holding it: its platform was given the value. That is the honest result; detection, not prevention, is what a remote run offers.
- Preflighting or running a second remote agent on the same exposed server moves the sign-in to that agent's person; the first one's access token keeps working.
- Idle time ends a remote run. A platform that pauses for longer than 30 seconds mid-task ends it early; the scenario's `max_minutes` bounds the wait.

## Alternatives considered

- **One engine port forward for the ingress.** Faster per connection, but it adds a second way into the engine and works only for the Lima driver as written.
- **The ingress holds the certificate.** Matches decision 0009's first wording, but the mirror would hold a publicly trusted private key.
- **Approval with a one-time code.** No sign-in page to build, but no production company has such a page, and a careful platform could notice.

## To verify

- Behind a real reverse proxy with a public certificate, from a vendor platform. It has been tested with a reference client on the same machine.
