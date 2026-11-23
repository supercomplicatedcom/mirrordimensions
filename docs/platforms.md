# Platforms

What runs where, and what has been measured. The rules are in the build spec ("Platforms and the engine") and the reasons in `docs/decisions/0001` to `0006`. Keep this page current: every measurement and every verified or failed assumption goes here in the same pull request that finds it.

## Support

| Host | Engine driver | Engine architecture | Boundary | Status |
| --- | --- | --- | --- | --- |
| macOS on Apple Silicon | `lima` (Virtualization.framework) | arm64 | Dedicated VM | Supported |
| Linux x64 | `lima` (QEMU and KVM), default | x64 | Dedicated VM | Supported |
| Linux x64 | `host`, opt-in | x64 | Host | Supported |
| Windows 11 x64 | `wsl` (dedicated WSL2 distribution) | x64 | Shared VM | **Experimental: not yet verified on real hardware** |

## Prerequisites

| Host | Needs |
| --- | --- |
| macOS | A supported macOS release (to be pinned in M0.5); Rosetta for Linux (`softwareupdate --install-rosetta`); Lima, installed by `mirror engine setup` if missing |
| Linux | KVM (`/dev/kvm` readable by the user) for the `lima` driver; or Docker Engine and gVisor for `host` |
| Windows | WSL2 installed (`wsl --install`, needs admin rights and a restart, done once by the user); virtualization enabled in firmware |

## Footprint

To be measured in M0.5 (empty engine) and M2 (prototype world with both twins, browser and base snapshot). Defaults for `mirror engine setup` are set from these numbers.

| Measurement | macOS arm64 | Linux x64 | Windows x64 |
| --- | --- | --- | --- |
| Engine setup download | | | |
| Engine idle memory | | | |
| Disk: engine, images | | | |
| Disk: one world, base snapshot | | | |
| Memory: world up, one agent, browser | | | |
| Restore time, base snapshot (target under 60 s) | | | |
| Event delay, gateway to host `events.jsonl` (budget 2 s) | | | |
| Emulated images and added latency | | | |

## Verification log

One row per assumption from the decision records, as it is checked.

| Date | Host | Assumption | Result | Note or decision |
| --- | --- | --- | --- | --- |
| 2026-11-22 | macOS | Docker Desktop kernel name is visible to containers | Confirmed: `6.12.67-linuxkit` | Reason for 0002 |
| 2026-11-22 | - | Official Mattermost Team Edition image is amd64 only | Confirmed from Mattermost's support article | 0005 |
| 2026-11-22 | - | gVisor supports arm64 | Confirmed from gVisor's FAQ | 0005 |
| 2026-11-22 | - | gVisor runs under WSL2 | Not documented; unverified | 0002 |
