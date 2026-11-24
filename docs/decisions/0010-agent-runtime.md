# 0010. Agents run as hardened containers in the dedicated engine VM; gVisor becomes opt-in

Status: Accepted (owner) · Date: 2026-11-23 · Milestone: M1 · Supersedes: the gVisor parts of 0001, 0002, 0004 and 0005

## Context

The spec made gVisor the sandbox for agent and browser containers. While M0.5 was being built and M1 started, the engine showed that gVisor announces itself to any unprivileged process, and none of it can be configured:

| What the agent sees | Value under gVisor (release-20261116.0) |
| --- | --- |
| `uname -r`, `/proc/version` | `4.19.0-gvisor`, built `Sun Jan 10 15:06:54 PST 2016` (hard-coded in `pkg/sentry/kernel/version/version.go`) |
| `dmesg`, readable without privileges | `Starting gVisor... Mounting deweydecimalfs... Reticulating splines...` |
| `/proc/gvisor/` | Present, with `checkpoint` and `spec_environ` |

A determined agent can also find gVisor through sparse `/proc` and `/sys`, syscall differences and timing. That breaks the guarantee that "the agent must not know", which outranks convenience. Hiding the strings would mean maintaining a patched runtime that still could not hide gVisor from real probing. A microVM per agent would give both properties, but it needs nested virtualization, which first-generation Apple Silicon Macs and most WSL setups lack.

## Decision

1. **Agents and the managed browser run as ordinary containers, hardened, inside the dedicated engine VM.** The VM is the isolation boundary. It is already firewalled, shares nothing with the host, and holds only the sandbox (0002, 0004). The agent sees an ordinary Ubuntu cloud kernel.

2. **Hardening on every agent and browser container:**
   - all capabilities dropped;
   - `no-new-privileges`;
   - Docker's default seccomp profile and Ubuntu's `docker-default` AppArmor profile;
   - memory and process limits;
   - no host mounts and no Docker socket;
   - paths that identify the engine's hardware masked (`/sys/class/dmi`, `/sys/devices/virtual/dmi`).

   User-namespace remapping is **not** on by default. It shows up in `/proc/self/uid_map` (`0 100000 65536` instead of `0 0 4294967295`), which ordinary production containers do not have. It is available as opt-in hardening, reported as a disclosed difference.

3. **gVisor stays installed and becomes an opt-in extra layer:** `isolation.runtime: gvisor` in the manifest. Results then carry the disclosed difference "runtime is detectable (gVisor)". That is still the right choice for an agent that runs on gVisor in production (for example Cloud Run or GKE Sandbox), where it is no tell at all.

4. **Isolation levels are redefined:**

   | Level | Means |
   | --- | --- |
   | `full` | Agent and browser run in hardened containers inside a dedicated VM (`lima` driver), and the egress, inside-out, engine-hardening and naming suites all pass |
   | `reduced` | The suites pass, but the boundary is weaker: a shared VM (`wsl`) or the host itself (`host` driver) without gVisor, or a hardening step could not be applied |
   | `failed` | Any suite fails. `mirror run` refuses to start |
   | `remote` | Unchanged: vendor-hosted agents reaching the world through its MCP ingress |

   On the `host` and `wsl` drivers, `isolation.runtime: gvisor` brings the level back to `full`, with the "runtime is detectable" difference disclosed.

5. **Tracing inside the agent's container moves from gVisor to eBPF in the engine.** Coverage needs process starts, file opens and sockets of the agent's container, recorded from outside it. Without gVisor's runtime monitoring, that comes from eBPF programs in the engine kernel (proposed: Tetragon, Apache-2.0), verified when coverage is built in M5. Nothing is added inside the container.

6. **Emulated agents.** With no gVisor in the way, an amd64-only agent image can run under Rosetta on Apple Silicon at `full`. The architecture and CPU differences are disclosed (decision 0005, `docs/tells.md`).

## Consequences

- The kernel, `dmesg` and `/proc` look like an ordinary Ubuntu cloud host. The gVisor tells are gone by default.
- Isolation rests on one strong boundary (a hardware VM) plus container hardening, instead of two boundaries. An escape from a container lands in a throwaway, firewalled VM that holds no host files, has no route to the host, and holds only this sandbox. On a laptop it never lands on the admin's machine.
- **Windows and the Linux host driver become `reduced` by default**, because their boundary is weaker. An operator who wants `full` there uses gVisor and accepts that it is detectable.
- Apple Silicon keeps two disclosed differences: the Apple CPU in `/proc/cpuinfo`, and the architecture if production runs on x64.
- eBPF tracing becomes M5 work and needs its own verification on each driver.
- `mirror engine check` still checks that gVisor works, because it remains available.

## Alternatives considered

- **Patch gVisor.** Hides the strings, not gVisor. It means shipping a runtime build. Rejected by the owner.
- **A microVM per agent (Kata Containers, Firecracker).** Strongest, and undetectable, but needs nested virtualization that the supported Macs and WSL lack. Kept as a possible future driver option on Linux hosts and M3+ Macs.
- **Keep gVisor and disclose it.** Most agents could tell they are sandboxed. Rejected by the owner.

## To verify

- Docker's `MaskedPaths` host setting masks the DMI paths in the pinned Docker version (M1).
- Tetragon, or another eBPF tracer, runs in the engine on arm64 and x64 and records exec, file and socket events per container (M5).
- The default seccomp and AppArmor profiles do not break the reference agents or the managed browser (M4).
