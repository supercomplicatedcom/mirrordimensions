# 0003. The control plane runs natively on the host; everything crosses into the engine through the Docker API

Status: Accepted (owner) for running on the host; the rest Proposed · Date: 2026-11-22 · Milestone: M0, M0.5, M1

## Context

On Linux in the original spec the control plane, the Docker daemon and the containers shared one machine. With the engine in a VM (0002) they are on two machines: the host, where the user edits `mirror.yaml` and opens reports, and the engine, where everything runs. Something has to carry commands, events, files and seeding traffic between them, without giving the sandbox a path back to the host.

## Decision

**1. Where things live**

| Thing | Lives on | Why |
| --- | --- | --- |
| `mirror` CLI, runner, evaluator, service layer, portal | Host, native Python | Users edit and open files with their own tools; the portal binds to the host's loopback |
| `mirror.yaml`, agent files, scenarios, `world.json`, canary list | Host project folder | Never enter the engine (unchanged rule) |
| Run artifacts: events, bodies, `result.json`, `ledger.json`, `report.html` | Host project folder (`.mirror/runs/`) | Read by the user and the portal |
| Root CA key and certificate | Host (`.mirror/ca/`), copied into the gateway container at start | Unchanged rule: never in a container the agent can reach |
| Twin volumes, snapshots, images, gateway certificate cache | Engine | Size and speed: restores must not cross the VM boundary |
| Snapshot index (name, content hash, size, time) | Host (`.mirror/snapshots/index.json`) | State is derivable from files and the engine |

**2. One way across: the Docker API.** The control plane talks to the engine only through the Docker API, at an endpoint the engine driver provides:

| Host | Endpoint | Who can use it |
| --- | --- | --- |
| macOS, Linux `lima` | Guest Docker socket forwarded by Lima to a Unix socket in the mirror's host data folder | Owner only (file mode 0600, folder 0700) |
| Windows `wsl` | Docker daemon on the engine's loopback, reached through WSL's localhost forwarding, protected by mutual TLS with a client certificate created at setup | Holder of the client key, stored under the user's profile with an owner-only ACL |
| Linux `host` | The host's Docker socket | As configured by the operator |

No folder is shared between host and engine. Files cross only through the Docker API:

- **Into containers:** the root certificate, leaf certificates and credentials are copied in with the archive API, never mounted (this also keeps host paths out of `/proc/self/mountinfo`).
- **Events during a run:** every in-engine event source (gateway, resolver, sinkhole, browser observer, runtime tracing) writes JSON Lines to its standard output or a per-run volume. The control plane follows them through the API and writes `events.jsonl` on the host. The live view's two-second delay requirement applies end to end, across the boundary.
- **Bodies and artifacts at run end:** copied out of the per-run volume with the archive API, then the volume is deleted.

**3. The control relay: how the host reaches twins.** Adapters seed twins, issue identities, run checks and dump state through each product's HTTP API on the system network. The host has no address there. A small relay container sits on the system network only (never the agent network). The control plane opens a stream to it with Docker `exec` and runs HTTP over that stream, one connection per stream. No twin port is ever published to the engine's network interfaces or to the host. The same relay is used in `host` mode, so there is one code path.

**4. Browser mode.** The original spec allowed a browser-mode agent to run "as a local process during development". That would need a path from the host into the agent network, so it is removed: on every host, the program that drives the browser runs in a container in the engine. The runner's read-only observer session still needs to reach the browser's DevTools endpoint. It must do so without putting the control plane on the agent network and without adding a helper process inside the browser container. The design is open and is settled in a decision note at the start of M4. One option: give the browser container a second interface on a network only the relay joins, with DevTools listening there.

**5. Time.** The engine's clock is the single reference for event timestamps. At run start, and every minute during a run, the runner measures the host-to-engine offset (`Engine.clock_offset()`) and stamps its own events on engine time. If the offset exceeds one second at run start, the run refuses and names the fix (`mirror engine start` resynchronizes the clock). Ordering inside the timeline still uses the per-source sequence numbers, so clock skew can never reorder a source's own events.

**6. Sleep.** Builds, creation stages and runs keep the host awake (macOS power assertion, Windows `SetThreadExecutionState`, Linux `systemd-inhibit` when available). If the host sleeps anyway, the clock jump is detected; the run ends with status `errored`, reason `host slept`, exit code 4.

**7. Portable host code.** Everything host-specific lives in `src/mirror/hostos/`; nothing else checks the operating system.

| Concern | Rule |
| --- | --- |
| Paths | `pathlib` everywhere. Keep run artifact paths short, so a deep project folder on Windows stays under 260 characters |
| Folders | Host-level config and data in the platform's standard folders (via `platformdirs`): engine settings, Docker client keys, Lima home |
| Owner-only files | POSIX modes 0600 and 0700 on macOS and Linux; on Windows an ACL granting only the current user, applied on create and checked by `mirror doctor` |
| Text files | Always UTF-8, always `\n` line endings, written in binary mode, so generated files are byte-identical on every host |
| Names | Ids, slugs and file names must be unique ignoring case, because macOS and Windows file systems are case-insensitive. `mirror validate` enforces it |
| Lock | `.mirror/lock` through one portable lock helper (no `fcntl`-only code) |
| Interrupts | Ctrl+C and console close end a run cleanly on every host; no reliance on `SIGTERM` |
| Terminal | ANSI color on Windows Terminal and modern consoles; `NO_COLOR` and `--no-color` respected; plain text when not a terminal |
| Opening things | `mirror portal` and `mirror report --open` use the platform's default browser |

## Consequences

- Users install one Python package on their own OS and never work inside the VM.
- A single transport (the Docker API) is the only thing to secure between host and engine.
- Seeding thousands of objects through exec streams may be slower than direct HTTP. Measured in M2; if too slow, seeding can batch, or run as a short-lived seeding container on the system network that is removed afterwards with its traces (seeding traces are already removed in creation stage 5).
- Snapshots no longer live in `.mirror/snapshots/` on the host. Moving a world to another machine means `mirror world create` there (it is deterministic), not copying snapshots. Export and import of snapshots is later work.

## Alternatives considered

- **Control plane inside the VM** with a thin host forwarder. Simpler code (Linux everywhere), but users would cross into the VM to edit files and open reports, and on Windows the WSL file share is slow. Rejected by the owner.
- **Shared folder for run artifacts** (virtiofs on macOS, `\\wsl$` on Windows). Fast to write, but it is a host path visible to the VM and anything that escapes into it. Rejected.
- **Publishing twin ports to the host's loopback** for seeding. Every local user and every browser tab could reach twin admin APIs. Rejected.

## To verify

- Docker API archive and exec streaming behavior through a Lima-forwarded socket and through WSL localhost forwarding with TLS.
- Event delay end to end: gateway event to `events.jsonl` on the host within the live view's two-second budget, measured on macOS and Linux.
- Throughput of HTTP over exec streams for seeding the prototype world (25 people, 150 issues, 2,000 messages).
- WSL localhost forwarding in both NAT and mirrored networking modes (the mode is a per-user global setting the mirror must not change).
