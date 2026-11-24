# 0016. Coverage inside the agent's container: Tetragon in the engine, and connections instead of byte counts

Status: Proposed · Date: 2026-11-24 · Milestone: M5 · Settles: decision 0010's "To verify" for eBPF tracing

## Context

Complete coverage needs what happens inside the agent's container: process starts, and the sockets it opens. It must be recorded from outside the container, with nothing added inside it (decision 0010, point 5). The spec's second reconciliation compares packet and byte counters on the agent's interface with what the gateway, resolver and sinkhole recorded, "within a small tolerance for protocol overhead".

Measured in the engine (Ubuntu 26.04, kernel 7.0, arm64, Docker 29.10):

- **Tetragon v1.8.0** (Apache-2.0) runs as a container in the engine's own namespaces (`--pid=host --cgroupns=host --privileged`, `/sys/kernel` read-only, no network). It reports every process start with its container (the `docker` field, the first 31 characters of the container id).
- A tracing policy on `tcp_connect` and `udp_sendmsg` reports each connection attempt with its destination and the program that made it. A refused attempt to `1.1.1.1:80` and an accepted one to the gateway were both reported, attributed to the container.
- Byte counts do not reconcile usefully. The gateway terminates TLS, so what it records is the decrypted exchange, while the interface carries TLS records, handshakes, retransmissions and keep-alive. "Small tolerance" has no fixed value that would catch a missed exchange without failing honest runs.

## Decision

1. **The engine's tracer is Tetragon.**
   - Image `quay.io/cilium/tetragon:v1.8.0`, pinned by digest.
   - It runs as `auditd-01`, started with the sandbox, on no network, in the engine's namespaces.
   - It is the only privileged container in the engine. Nothing from it runs in, or is reachable from, any container on the agent or system networks.
   - Its events reach the host through the Docker API like every other capture source. The runner keeps only the agent's own container, by id, which it registers between creating the container and starting it, so no early process is missed.
2. **Two new host events:** `process.exec` (program, arguments, container) and `socket.connect` (program, protocol, destination).
3. **Reconciliation 2 compares connections, not bytes.** Every connection the kernel saw from the agent's container must be one of three things:
   - to the gateway (80 or 443), with at least one exchange captured;
   - to the resolver (53), with lookups recorded;
   - refused, and recorded by the engine firewall.

   Anything else is unexplained, and the run's coverage is incomplete. This keeps the spec's intent, "independent sources agree", with a test that does not need a tolerance.
4. **Reconciliation 3** lists every program the container ran, and which of them opened sockets, matched through reconciliation 2.
5. **`ip_send_skb` reports only packets that are not TCP.** The kernel's own TCP replies (acknowledgements and resets for other connections, such as the gateway's upstream) leave through `ip_send_skb` from interrupt context, and Tetragon credits them to whichever process was running (seen live on 2026-11-24, with the packets' protocol `IPPROTO_TCP` and source the gateway's uplink address). A container's own TCP connections are traced at `tcp_connect`, so TCP packets at `ip_send_skb` are ignored and the others keep their real protocol.
6. **Without the tracer**, the `host` channel is `not_captured` and both reconciliations fail. The run is marked `coverage: incomplete` and exits with code 4, and its result says so plainly.

## Consequences

- Every run on the lima engine can reach `coverage: complete` without anything inside the agent's container.
- The engine holds a privileged container. It has no network, and the agent cannot see it: it is not on any network the agent is on, and its kprobes are not visible without capabilities the agent lacks. The inside-out suite should still confirm that no tracing filesystem is readable from an agent container (M5 follow-up).
- Tetragon adds a 418 MB image and some kernel overhead, so `mirror engine check` should show it working.

## Alternatives considered

- **Interface byte counters with a tolerance.** Rejected, for the reasons above.
- **conntrack accounting.** It reports the same flows as the tracer, but not which program opened them, and it needs `nf_conntrack_acct` turned on in the engine.
- **gVisor runtime monitoring.** Rejected in decision 0010: gVisor announces itself.
- **Falco.** Comparable, but it needs a kernel driver or a larger rule set for the same events. Tetragon's policies are smaller and its process events already carry the container.

## To verify

- The same on the WSL and host drivers (M6 platform pass).
- No tracing filesystem (`/sys/kernel/tracing`, `/sys/kernel/debug`) is readable from an agent container (M5 follow-up, inside-out suite).
