# 0001. macOS, Windows and Linux are supported with equal guarantees

Status: Accepted (owner) · Date: 2026-11-22 · Milestone: M0, M0.5

## Context

The first build spec targeted one Linux machine and treated macOS and Windows as development hosts at `reduced` isolation, because gVisor runs only on Linux. Most of the people who will try the project, write scenarios and approve agent rollouts work on Macs and Windows laptops. If those machines can only produce "reduced" results, the local profile is a demo, not a test range.

## Decision

1. **Supported hosts**

   | Host | Architecture | Support level |
   | --- | --- | --- |
   | macOS on Apple Silicon (current and previous major release) | arm64 | Supported |
   | Windows 11 with WSL2 | x64 | Supported, labeled **experimental** until verified on real hardware (see 0006) |
   | Linux (a current Ubuntu LTS and Debian stable) | x64 | Supported |

   Not supported: Intel Macs, Windows on ARM, Windows 10, Linux arm64 hosts. They may work; nothing is tested or promised. Linux arm64 is the easiest to add later, because the macOS engine already runs arm64 Linux.

2. **Parity.** A run on any supported host gives the same guarantees: the same isolation levels with the same definitions, the same egress, inside-out and coverage suites, and the same result format. A `full` result from a Mac counts as evidence exactly like one from a Linux server.

3. **How parity is achieved.** Every host runs the sandbox inside a Linux VM the mirror manages (0002), with gVisor inside it. The control plane runs natively on the host (0003).

4. **Honest differences are reported, not hidden.** Each `result.json` records a `platform` block: host OS and architecture, engine kind, engine architecture, guest kernel, gVisor version, isolation boundary and any emulated images. Where a host cannot meet a guarantee (for example gVisor not working under WSL2), the run says `reduced`, exactly as on a Linux host without gVisor.

## Consequences

- One manifest, one set of scenarios and one result format work on all three hosts. `mirror.yaml` holds nothing host-specific; engine settings live in host-level configuration.
- Host-side code must be portable: paths, file permissions, locks, line endings, signals, sleep and opening a browser (0003).
- A new milestone, M0.5 Engine, comes before the sealed network.
- Windows cannot be called fully supported until someone runs the suites on a Windows machine.

## Alternatives considered

- **Linux only, macOS and Windows for development at reduced isolation.** The original spec. Rejected by the owner: most users would never see a trustworthy result.
- **Parity later.** Ship reduced isolation first and add the VM later. Rejected: the VM changes where state lives and how the control plane reaches containers, so adding it later means rework in every milestone.

## To verify

- The oldest macOS version that supports everything 0002 needs (Virtualization.framework with Rosetta for Linux and virtiofs).
- The oldest Windows 11 build with the WSL features 0002 and 0004 rely on (systemd in WSL, per-distribution `wsl.conf` settings).
