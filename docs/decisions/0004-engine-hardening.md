# 0004. The engine shares nothing with the host and cannot reach it

Status: Proposed · Date: 2026-11-22 · Milestone: M0.5, M1

## Context

Putting the sandbox in a VM adds a boundary, but VM tools are built for convenience and connect the VM to the host in several ways by default. Each one is either an exit or a tell:

| Default behavior | Lima | WSL2 | Risk |
| --- | --- | --- | --- |
| Host folders mounted in the VM | Home folder, read-only | Every Windows drive under `/mnt/c` etc., read-write | Real data and credentials reachable after an escape; host paths are a tell |
| Run host programs from the VM | No | Yes (`interop`: any `.exe` can be run from Linux) | Direct escape to the host |
| Host's loopback services reachable from the VM | Yes, through the user-mode network's host address (`host.lima.internal`) | Yes, through the Windows host address, or directly in mirrored mode | The portal, other local services and the Docker endpoint are reachable |
| Automatic port forwarding of the VM's listeners to the host | Yes | Yes (localhost forwarding) | Twin or gateway ports appear on the host |
| Host's `PATH`, environment or hostname inside the VM | No | `PATH` appended by default | Host details leak into the guest |
| Shared mount across distributions | No | `/mnt/wsl` | Other WSL distributions can see the engine |

## Decision

**1. Nothing shared.**

- Lima: `mounts: []`. No virtiofs or 9p shares. Automatic port forwarding off. The only forward is the Docker socket, guest to host (0003).
- WSL: the engine distribution's `/etc/wsl.conf` sets `[automount] enabled = false`, `mountFsTab = false`; `[interop] enabled = false`, `appendWindowsPath = false`; `[boot] systemd = true`. It does not touch the user's global `.wslconfig`, because that would change their other distributions.
- `mirror doctor` checks these settings from inside the engine every time, not only at setup.

**2. No route from containers to the host.** An nftables policy in the engine, installed at setup and checked by `doctor`:

- Traffic from every container network to the host-alias addresses (Lima's host address, the Windows host address in NAT mode, the host's addresses in mirrored mode) and to the engine's own management addresses is dropped and logged.
- Only the gateway's outside network may route beyond the engine at all, and only to the addresses the model routes resolve to (the same allow-list the gateway enforces, enforced a second time at the engine edge). This is the "second, independent egress block at the network perimeter" the product spec asks for.
- Image pulls happen during setup and build, from the engine's own network namespace, not from any container network, and only while no world is up.

**3. The engine is not a place to keep things.** No mirror source code, project files, world files or credentials are stored in the engine beyond what a running container needs (the gateway's CA copy, injected credentials). The provisioning script installs packages and writes configuration, then leaves nothing of the repository behind.

**4. Kernel and VM identity.** Agent and browser containers run under gVisor, which presents its own kernel and hides the engine's (`linuxkit`, `microsoft-standard-WSL2` or the guest's distribution kernel). Without gVisor, an agent container sees the engine kernel, so:

- The naming lint's forbidden list gains `lima`, `linuxkit`, `wsl`, `microsoft-standard`, `orbstack`, `colima`, `docker-desktop` and `rosetta`, checked in `uname`, `/proc/version`, `/proc/cmdline`, `/proc/cpuinfo`, DMI data, mounts and environment.
- A finding there marks the run `reduced` and lists the tell in `result.json`.
- gVisor's own signatures (its synthetic kernel version and boot messages) are a tell on every host, not just Mac and Windows. They are recorded in `docs/tells.md` as open, to be closed as part of M1.

**5. The egress and inside-out suites gain engine-specific items** (see the build spec, "Platforms and the engine"):

- Reach the host's loopback services (a listener the test starts on the host's `127.0.0.1`) from the agent network and from the system network.
- Resolve and reach `host.lima.internal`, `host.docker.internal`, `gateway.docker.internal` and the WSL host address.
- Find any host folder, Windows drive or `/mnt/wsl` in the engine.
- Run a Windows program from the engine (Windows only).
- Find the Docker endpoint or client keys from any container.

## Consequences

- An escape from gVisor lands in a VM that holds only the sandbox and has no path to the host's files, programs or services.
- On Windows, other WSL distributions still share the VM and kernel (0002); `/mnt/wsl` is unmounted inside the engine distribution, but this cannot stop another distribution's root user. Recorded as `boundary: shared-vm`.
- The admin cannot simply copy files into the engine through a shared folder for debugging. `mirror engine shell` is the supported way in.

## Alternatives considered

- **Keep the defaults and rely on gVisor.** Rejected: "Assume the sandbox is already escaped. Host and network controls must hold on their own" (product spec).
- **Change the user's `.wslconfig`** to force NAT mode or a custom kernel. Rejected: it changes every WSL distribution the user has.

## To verify

- The exact Lima and WSL settings above against their current documentation.
- That nftables rules in the engine apply to Docker bridge traffic as expected alongside Docker's own rules (the `DOCKER-USER` chain or its nftables equivalent in the pinned Docker version).
- How WSL mirrored networking mode presents host addresses inside the distribution, and that the drop rules cover them.
