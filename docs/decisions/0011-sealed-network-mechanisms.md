# 0011. How the sealed network is built: mechanisms that differ from the spec

Status: Proposed · Date: 2026-11-23 · Milestone: M1

## Context

The build spec named mechanisms for the sealed network that had not been checked against the tools: a sinkhole container, Docker Compose, mitmproxy minting certificates, and a resolver that fails unknown names. Building M1 in the engine showed where each one works as written and where it does not. CLAUDE.md asks for a design note whenever a named mechanism turns out not to work as described.

## Decision

**1. The engine's edge firewall is the sinkhole.**
- Agent and system networks are ordinary Docker bridges with a default route, so every attempt produces a real packet.
- The edge firewall (decision 0004) drops and logs each packet a container sends to anything but another container on its own network.
- A log relay (`klog`: no network, `CAP_SYSLOG`, reading `/dev/kmsg`) streams those lines through the Docker API, and the host turns them into `egress.blocked` events. They are measured at 0.03–0.05 s, against a budget of 1 s.

Two findings made this work:
- **IPv6.** The engine has no IPv6 route out, so the kernel drops IPv6 packets before the forward hook, unlogged. A prerouting rule drops and logs packets with no route.
- **Neighbour discovery.** It must be allowed from containers to the engine. Without it a container never learns its gateway's address, its packets never leave it, and there is nothing to record.

Link-local multicast is dropped without logging, since it cannot leave the network.

**2. The Docker API, not Compose.**
- The sandbox is created directly through the Docker API (`network/sandbox.py`), with static addresses and files copied in through the archive API.
- Compose would need a `docker compose` client on the host, or a shell into the engine. Decision 0003 allows neither.
- `compose/` is not created. The seam the spec wanted, swapping the runtime later, sits in `engine/docker_api.py` and `network/sandbox.py`.

**3. Certificates are minted on the host, not by mitmproxy.**
- mitmproxy's own leaves are valid from "two days ago" for 199 days, and can carry the upstream's internal address in their alternative names.
- Instead, the control plane mints one certificate per hostname with the install's CA: issued 20 to 160 days ago (chosen from the seed), valid 397 days, the hostname as its only name, server-auth usage.
- mitmproxy loads them with `--certs`. The CA key never enters the gateway.

**4. The gateway refuses unknown names before TLS and presents itself as nginx.**
- The gateway runs mitmproxy in reverse mode. Its default upstream is a closed local port, with `connection_strategy=lazy`.
- An unknown name is passed through to that closed port, so the client sees an ordinary refusal and no certificate. An earlier version presented mitmproxy's own CA certificate, which the inside-out checks caught.
- A request whose `Host` does not match its TLS name is refused and logged as `route.unknown_host`.
- mitmproxy's own error pages (`Server: mitmproxy 12.3.1`, carrying the internal error message and the upstream's address) are replaced with nginx's exact pages and headers. This uses replacements in the add-on, valid for the pinned mitmproxy version, and `mirror doctor` checks it on every run.

**5. The resolver answers like a restricted corporate resolver.**
- CoreDNS runs plugins in a fixed compiled order. `hosts` answers the world's names and falls through to `file`, which serves an empty root zone.
- Unknown names therefore get NXDOMAIN with the root's SOA record. A catch-all `template` would run before `hosts`, and `hosts` alone answers SERVFAIL.
- Nothing is forwarded to another resolver.

**6. Names the agent can see.**
- Networks: `corp-lan`, `corp-apps`, `corp-uplink`. Containers: `ns1`, `edge-proxy-02`, `app-NN`, `klog`.
- Docker's embedded DNS answers reverse lookups with `name.network` (for example `edge-proxy-02.corp-lan.`), so these names are visible to the agent and must look ordinary.
- Custom bridge names are never used: the firewall matches Docker's `br-*` bridges, and a custom name would bypass it.

**7. Engine updates are applied in place.**
- `mirror engine setup` re-applies the provisioning script when it has changed. Docker restarts only if its own configuration changed, so an update never stops a running world without cause.

## Consequences

- Every egress attempt in the spec's list fails and is recorded within a second. The rest is also proven on the owner's Mac by `mirror doctor`:
  - the separation of the three networks;
  - the inside-out scan;
  - naming across the environment, hostname, hosts file, resolver, mounts, kernel, hardware identity, reverse DNS, certificates, headers and error pages;
  - gateway transparency, adding 2.6 ms per plain HTTP request;
  - redaction.
- The replacements in the gateway add-on are tied to mitmproxy 12.3.1. A new mitmproxy version needs the error-page check to pass before it is pinned.
- One world at a time per engine, because the infrastructure names are fixed. That matches the prototype.

## To verify

- The same suite on the Linux `lima` engine in CI.
- `/etc/resolv.conf` in agent containers still says "Generated by Docker Engine" (`docs/tells.md`, row 8). Decide in M4, when agent containers exist, whether to replace it.
