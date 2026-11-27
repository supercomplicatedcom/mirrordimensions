# 0027. Doctor reports each guarantee on its own

Status: Accepted (owner, 2026-11-27).

## Context

`mirror doctor` ended with a single verdict, `Isolation: full` or `Isolation: failed`. Any failing check set it to failed, including the checks that have nothing to do with the seal: the gateway's added latency, and the naming checks. In a first run by someone new to the project, every egress, separation, inside-out and capture check passed, but the gateway added 10.5 ms on a busy computer (the limit is 10 ms). Doctor reported "Isolation: failed", which reads as "something can get out" when nothing could.

The project makes three guarantees, and the checks already fall under them.

## Decision

1. Doctor reports one verdict per guarantee:
   - **Isolation** (`full`, `reduced` or `failed`), from the egress, ingress, separation and inside-out checks: nothing leaves the sandbox. `reduced` keeps its meaning (a weaker boundary than a dedicated VM).
   - **Coverage** (`complete` or `incomplete`), from the capture checks: everything the agent does is recorded.
   - **Undetectability** (`full` or `failed`), from the naming and transparency checks: nothing the agent sees reveals a test. The gateway's added latency is here: it is a timing signal an agent could measure, not a way out.
2. Each verdict that fails names its first failing check. A latency failure adds a note that a busy computer raises it.
3. `mirror doctor` exits 1 when any guarantee does not hold, as before.
4. `mirror world create` stops when isolation or coverage fails. When only undetectability fails, it reports which checks failed and goes on; `mirror doctor` still fails.
5. The portal's Health screen and the operator MCP server show all three verdicts. `doctor.json` keeps `isolation` with its meaning unchanged, and adds `coverage` and `undetectability`.

## Consequences

- "Isolation: failed" now means the seal failed. A slow gateway is reported as `Undetectability: failed: latency the gateway adds…`.
- A run's own isolation check (the fast subset of doctor at the start of every run) is unchanged.
- The exit-gate workflow's check for `Isolation: full` keeps working. It no longer catches a latency or naming failure; doctor's exit code still does.
- Two checks that said "n/a (covered in M2)" now run. A twin asked to fetch a URL on the host, where the control plane listens, is checked live: Gitea refuses local addresses itself, and an attempt that got as far as the firewall would be recorded as blocked. Seeding traces pass when the world has been built, because `mirror build` refuses to save a snapshot with traces and every run starts from that snapshot.
