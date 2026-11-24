<!-- SPDX-FileCopyrightText: 2026 Supercomplicated LLC -->
<!-- SPDX-License-Identifier: Apache-2.0 -->
# 0013. The model gateway: one pinned upstream per route

- Status: proposed
- Date: 2026-11-23
- Milestone: M4

## Context

The build spec ("Rules for the model gateway") requires the following:

- **The agent reaches its model only through the gateway**, under the provider's own hostname.
- **The real credential is added outside the sandbox.**
- **Only inference paths are forwarded.**
- **Provider-hosted tools are refused, flagged or allowed.**
- **Streams arrive incrementally and are captured whole.**
- **A self-hosted route reaches its one address and port and nothing else.**

## Decision

- **Names.** Model hosts resolve to the gateway, as every world hostname does. They get leaf certificates from the company's root, the way a corporate TLS-inspecting proxy presents them.
- **One upstream per route.**
  - At `mirror up`, the control plane resolves each route's upstream on the host. It never resolves from inside the sandbox.
  - The gateway forwards to that pinned address and presents the provider's own name as SNI, so the upstream certificate is still verified against that name.
  - The engine's firewall set `egress_allow` holds (source, destination, TCP port) triples. It holds exactly one triple per route, from the gateway's uplink address only.
  - The gateway's default route is the uplink network (Docker `GwPriority`).
  - `mirror down` empties the set.
- **Credentials.**
  - The agent is deployed with the provider's usual variable, for example `ANTHROPIC_API_KEY`. It holds a placeholder in the provider's key format, derived from the world seed.
  - The gateway removes every credential header the agent sent and adds the real one, read from the host's environment.
  - The real value exists only in the gateway's configuration and is redacted from every capture.
- **Inference only.** A per-provider list of (method, path) pairs. Anything else gets the provider's own not-found error, and a `model.refused` event.
- **Hosted tools.** These are detected by tool type prefix (for example `web_search_*` and `code_execution_*`) and by request fields (`mcp_servers`, `container`, `web_search_options`). Each `hosted_tools` setting has its own behavior:
  - **`block`** answers with the provider's 400.
  - **`flag`** forwards the request and emits `model.hosted_tools` with `action: flagged`. The runner (M5) marks the run `coverage: incomplete`.
  - **`allow`** forwards the request and records it.
- **Streams.** `text/event-stream` responses are passed through chunk by chunk and copied as they go. Each exchange emits `model.exchange` with the route, model, token counts, whether it was streamed, and the duration.
- **One event per call (M6).** The event table lists `model.request` and `model.response` under a `model` source. The gateway records one `model.exchange` per call instead, in the same way it records one `http.exchange` per request: a model call is one request and one answer, and one event keeps them together. It is filed under the `model` source, emitted right after the call's `http.exchange` and names it (`exchange`), which holds the raw bodies. The text the model wrote, taken from the whole answer or the stream, is stored on its own (`answer_ref`) for the suspicion scan and the report, and each run keeps every call's prompt and answer in its `model/` folder. `model.refused` and `model.hosted_tools` are `model` events too. Runs recorded before this are read the same way.
- **Builds.** An agent image is built over the Docker API with `network_mode=host`. Package installs then happen in the engine's own network namespace at build time, as CLAUDE.md requires. The image always runs on the sealed networks.

## Providers in this milestone

- **`anthropic`, `openai` and `self-hosted`** (OpenAI-compatible). Their paths, credential headers, hosted-tool types and error shapes were checked against the providers' current API references on 2026-11-23.
- **`azure-openai`, `google-vertex` and `aws-bedrock`** are accepted by the manifest but don't have provider rules yet.

## Verified (owner's Mac, 2026-11-23)

The self-hosted route was tested against a stub inference server outside Docker's networks, in its own network namespace in the engine, standing in for a company's own GPU host:

- **Whole and streamed answers** reached an agent-position container, and both were captured with token counts.
- **The stub received the real key.** The agent held a placeholder, and captured headers show `[redacted]`.
- **`/v1/files` got the provider-shaped 404** and never reached the stub.
- **A direct connection from the agent to the stub was blocked** and recorded as `egress.blocked`.
- **From the gateway itself, only the route's one address and port was reachable.** Another port on the same host, the engine, and a public address all timed out.

**A live cloud provider call** (owner's Mac and Anthropic key, 2026-11-24). `examples/agents/llm-example` ran `fix-failing-test` with a `provider: anthropic` route:

- The engine firewall held exactly one triple for the route: the gateway's uplink address to `api.anthropic.com`'s pinned address on 443.
- The agent called `claude-opus-5-5` through the gateway and got a 200 answer (148 tokens in, 240 out; run `r_a4a699d262`). The answer was captured as `model.exchange` with its body.
- The real key appears nowhere in the run's captures or results. Credential headers were recorded as `[redacted]`.
- Coverage was complete: every connection the agent's container opened went to the gateway or the resolver.

`mirror agent check` also passed for the route; Anthropic answered the empty probe with a 400, not a 401. Streaming against a cloud provider is still to be run live.
