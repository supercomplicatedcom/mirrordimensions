# Platforms

What runs where, and what has been measured. The rules are in the build spec ("Platforms and the engine") and the reasons in `docs/decisions/0001` to `0006`. Keep this page current: every measurement and every verified or failed assumption goes here in the same pull request that finds it.

## Support

| Host | Engine driver | Engine architecture | Boundary | Status |
| --- | --- | --- | --- | --- |
| macOS on Apple Silicon | `lima` (Virtualization.framework) | arm64 | Dedicated VM | Supported |
| Linux x64 | `lima` (QEMU and KVM), default | x64 | Dedicated VM | Supported |
| Linux x64 | `host`, opt-in | x64 | Host | Supported |
| Windows 11 x64 | `wsl` (dedicated WSL2 distribution) | x64 | Shared VM | **Experimental: not yet verified on real hardware** |
| macOS on Apple M3 or later, macOS 15+ | `lima` with `--microvm` (nested virtualization; Kata Containers with Firecracker for agents) | arm64 | Dedicated VM, microVM per agent | **Unverified: no M3 available.** The same runtime is verified on a Linux runner in CI |

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
| Engine setup download | Lima 2.3.0 (31 MB archive, 108 MB unpacked); Ubuntu 26.04 image (3.3 GB in Lima's cache); Docker and gVisor packages | | |
| Engine idle memory | 6 GB allocated; about 600 MB used by the idle guest | | |
| Disk: engine, images | 3.4 GB for the VM disk (40 GB, sparse) plus 3.3 GB of cached image: about 7 GB in all | | |
| Disk: one world, base snapshot | 6.4 GB used in the engine with Gitea, Mattermost, two PostgreSQL databases and the sandbox (images 3.4 GB); snapshot size in M3 | | |
| Memory: world up, one agent, browser | About 1.3 GB in use with both twins up (Mattermost 215 MB under Rosetta, Gitea 91 MB, databases 30 MB each, gateway 68 MB); agent and browser in M4 | | |
| Restore time, base snapshot (target under 60 s) | 10.1 s for both twins after arbitrary changes (an issue created, a repository deleted); state identical to the snapshot | | |
| `mirror build` from scratch (25 people, 6 repositories, 71 commits, 150 issues, 255 comments, 1,940 posts) | 104 s; snapshot 5 s; restore-and-compare 9.6 s | | |
| `mirror world create` from stage 1 (all eight stages, including the trace check and `mirror doctor`) | 149 s and 142 s on two runs; the two state dumps identical apart from Mattermost's own `system-bot`, which the product creates at a varying moment and the dump leaves out | | |
| `mirror up` (sandbox with two stub apps, images cached) | about 10 s | | |
| `mirror doctor` | 39 s | | |
| Managed browser (M4): image, memory, one `browser-basic` run | Image 3.57 GB (Playwright 1.65.2 base, Chromium 159 headless shell, arm64), pulled once; browser about 90 MB and observer about 19 MB during a run; a whole run (identity issued, browser and observer started, sign-in, comment, teardown) 10.8 s; `mirror agent check` 7 s | | |
| Event delay, gateway to host `events.jsonl` (budget 2 s) | | | |
| Emulated images and added latency | Mattermost (amd64 only) runs under Rosetta: median 12 ms for `/api/v4/system/ping` through the gateway | | |
| `mirror up` with Gitea and Mattermost (images cached) | 73 s, most of it Mattermost starting under Rosetta | | |
| First `mirror engine setup` | 354 s on a first-generation Apple Silicon Mac; a repeat run takes about 1 s | | |
| Clock offset, engine to host | +0.07 s after setup; over 30 minutes idle, 31 samples, never more than 0.163 s (limit 1 s); no host sleep | | |

## Verification log

One row per assumption from the decision records, as it is checked.

| Date | Host | Assumption | Result | Note or decision |
| --- | --- | --- | --- | --- |
| 2026-11-22 | macOS | Docker Desktop kernel name is visible to containers | Confirmed: `6.12.67-linuxkit` | Reason for 0002 |
| 2026-11-22 | - | Official Mattermost Team Edition image is amd64 only | Confirmed from Mattermost's support article | 0005 |
| 2026-11-22 | - | gVisor supports arm64 | Confirmed from gVisor's FAQ | 0005 |
| 2026-11-22 | - | gVisor runs under WSL2 | Not documented; unverified | 0002 |
| 2026-11-23 | macOS | Lima 2.3.0 with `vz`: `mounts: []`, `portForwards` that forward only the Docker socket and ignore every port, `vmOpts.vz.rosetta` | Confirmed from Lima's templates at v2.3.0; the engine starts with these settings | 0002, 0004 |
| 2026-11-23 | macOS | Rosetta for Linux runs amd64 Docker images in the engine | Confirmed: `uname -m` gives `x86_64` | 0005 |
| 2026-11-23 | macOS | gVisor runs on the arm64 engine | Confirmed: runsc release-20261116.0 | 0005 |
| 2026-11-23 | macOS | The Rosetta runtime is shared into the guest over virtiofs (`/mnt/lima-rosetta`) | Confirmed; not writable even by root in the guest. Allowed as the only share, and checked on every `mirror engine check` | 0004 |
| 2026-11-23 | macOS | The guest reaches the host's loopback at 192.168.5.2 | Confirmed (positive control); containers cannot, because of the edge firewall | 0004 |
| 2026-11-23 | macOS | Lima's download cache can be moved | No: it is always the OS cache folder (`~/Library/Caches/lima`). `mirror engine destroy` removes only the engine's own entries | 0002 |
| 2026-11-23 | macOS | The sealed network (M1): `mirror doctor` passes every check | Confirmed: egress events in 0.03–0.05 s, gateway adds 2.6 ms, isolation `full` | 0011 |
| 2026-11-23 | macOS | IPv6 attempts reach the firewall | Not at first: no IPv6 route out, and neighbour discovery was dropped. Fixed with a prerouting rule and by allowing neighbour discovery | 0011 |
| 2026-11-23 | macOS | gVisor hides the engine's kernel name | Yes, but gVisor reports `4.19.0-gvisor`: a tell of its own (docs/tells.md, row 5) | 0004 |
| 2026-11-24 | macOS | Hardened Chromium (no capabilities, `no-new-privileges`, default seccomp and AppArmor, unprivileged user) starts in the engine and serves DevTools on loopback | Confirmed with `--no-sandbox`; Chromium's own sandbox cannot start without capabilities | 0014 |
| 2026-11-24 | macOS | A second DevTools session sees the agent's input | No: DevTools has no event for another client's commands. The observer records the agent's own DevTools stream instead | 0014 |
| 2026-11-24 | macOS | A container sharing the browser's network namespace reaches DevTools on loopback, and passes the agent's connection through unchanged | Confirmed; `browser-basic` signs in to Gitea over valid TLS, comments, and every command, navigation and screenshot is captured, with the password redacted | 0014 |
| 2026-11-24 | macOS | Playwright's DevTools client compresses messages | Yes: permessage-deflate with context takeover; the observer inflates its copy | 0014 |
| 2026-11-24 | - | MCP's current revision and its HTTP transport | 2026-07-28: stateless Streamable HTTP, `server/discover`, required `MCP-Protocol-Version`, `Mcp-Method` and `Mcp-Name` headers; legacy `initialize` sessions allowed alongside (dual-era) | 0009 |
| 2026-11-24 | macOS | An agent with only MCP credentials completes `scripted-good`'s work through the world MCP server, and every message is captured | Confirmed: 5 exchanges, 10 `mcp.message`, 3 `mcp.call`; the server's 5 twin calls captured from its own address; reconciliation passes; `mirror up` with the MCP server 14 s | 0009 |
| 2026-11-24 | macOS | `mirror agent new` interactively in a terminal, then the preflight | Confirmed: six steps; role defaults from the generated company (engineer: Astrid Mbeki, Platform Lead, with her team's repositories and her channels); every check passed | - |
| 2026-11-24 | macOS | `mirror agent check` reaches a model route from the agent's network with the real credential, at no cost | Confirmed against the self-hosted route: an empty request answered 200 through the gateway; with the key unset the check fails and names the variable | 0013 |
| 2026-11-24 | macOS | Tetragon v1.8.0 runs in the arm64 engine from the engine's own namespaces and reports, per container, every process start and every outbound connection (`tcp_connect`, `udp_sendmsg`) | Confirmed: a refused attempt to `1.1.1.1:80` and an accepted one to the gateway were both reported, with the program and container | 0016 |
| 2026-11-24 | macOS | A whole run of `rotate-leaked-token` with `scripted-good` (restore, overlay, delivery, agent, scoring) | Passes in about 47 s; two runs give byte-identical `result.json` apart from the run id | 0015 |
| 2026-11-24 | - | Gitea 28's `access_token` table has no `has_used` column | Confirmed: use is `updated_unix > created_unix`, as Gitea's own `HasUsed` | 0015 |
| 2026-11-24 | - | Mattermost answers `GET /users/{id}/channels` for an account in no channel with 200 and a malformed body | Confirmed; the state dump treats it as no channels | 0015 |

| 2026-11-24 | macOS | A live Anthropic call through the gateway, with complete coverage | Confirmed: `llm-example` on `fix-failing-test`, `claude-opus-5-5` answered 200 through the gateway; the real key is absent from every capture; coverage complete once the tracer ignores the kernel's own TCP replies, which it had credited to the agent's process | 0013, 0016 |
| 2026-11-24 | Linux CI (nested) | The gateway adds under 10 ms with the engine's tracer running | On an Apple Silicon Mac, yes: 3.7 to 4.7 ms with the tracer, 3.2 to 3.9 ms without. On GitHub's runners, where the engine is a VM nested in GitHub's own VM on two CPUs, no: 10.2 to 16.2 ms with the tracer and 8.0 to 12.2 ms without, varying by runner; four CPUs made it worse. Filtering the tracer in the kernel (decision 0016) removed about 36% of its events | Owner's decision: the 10 ms limit applies on workstations; the CI job runs `mirror doctor --latency-budget-ms 20`, and the result names the limit used |
