# 0005. arm64 engines on Apple Silicon; emulation allowed for twins, not for agents

Status: Proposed · Date: 2026-11-22 · Milestone: M0.5, M2, M4

## Context

On Apple Silicon the engine is an arm64 Linux VM. Container images built only for amd64 need emulation. Lima with Apple Virtualization.framework can use Rosetta for Linux for amd64 programs, which is much faster than QEMU emulation.

Facts found while writing this:

- gVisor supports arm64 and amd64.
- **The official Mattermost Team Edition image is amd64 only.** Mattermost's support article says the official Docker images publish amd64 manifests only; arm64 images on Docker Hub are third-party and unsupported.
- Gitea publishes multi-architecture images including arm64.
- Customers' agent images are often amd64 only.

## Decision

1. **Engine architecture follows the host.** arm64 on Apple Silicon, x64 on Windows and Linux. No x64 VM on Apple Silicon: whole-machine emulation would be far too slow.

2. **Twins may run emulated.** Twins run on the system network under the default runtime, never under gVisor, and the agent sees them only through the gateway. An amd64-only twin image runs under Rosetta on Apple Silicon. Rules:
   - Use the product's official image unmodified, as on every other host. Do not switch to third-party arm64 images.
   - Record every emulated image in `result.json` under `platform.emulated`.
   - Measure emulated twin latency in M2. The behavior add-on's latency rules describe the product's behavior, so if emulation adds noticeable latency, `docs/platforms.md` says so and the defaults are calibrated per architecture.
   - If emulation proves unworkable for Mattermost, the fallback is building the upstream Mattermost server unmodified for arm64 on the host at build time, recorded in a new decision. Raise it with the owner first: it touches the "upstream software unmodified" and licensing rules.

3. **Agents and the browser are never emulated at `full` isolation.** Agent and browser containers must run under gVisor. Whether gVisor can run amd64 programs through Rosetta is unverified and unlikely, so:
   - On Apple Silicon an agent needs an arm64 (or multi-architecture) image. `mirror agent check` fails with the fix "publish an arm64 image of this agent, or run on an x64 host".
   - `--allow-emulated` runs an amd64-only agent under the default runtime with Rosetta. The run is `reduced`, and `result.json` says why.
   - The managed browser uses a multi-architecture Chromium image.

4. **Architecture is part of "same as production".** An agent that runs on x64 in production sees `aarch64` on Apple Silicon. Servers on arm64 are common, so this is a weak tell, but it is a difference from production. The agent file may declare `production_arch`. When it differs from the engine's, the result and report list it as a disclosed difference. It does not change pass or fail or the isolation level.

5. **Golden files do not depend on architecture.** `world.json` and the base `dump_state` golden files must be identical on arm64 and x64. Anything a twin reports that varies by architecture is excluded from `dump_state` as volatile.

## Consequences

- Full isolation on a Mac requires agents with arm64 images. This is the main practical cost of Mac parity, and onboarding must explain it plainly.
- Mattermost on Apple Silicon is slower and uses more memory under Rosetta.
- CI must check that golden files match on both architectures (0006).

## Alternatives considered

- **Third-party arm64 Mattermost images.** Rejected: unsupported, unverifiable, and they break "upstream software unmodified".
- **Emulate agents under gVisor with QEMU user-mode.** Very slow, and QEMU artifacts in `/proc` are a tell. Rejected.
- **Require x64 hosts for agent runs.** Defeats the owner's parity decision.

## To verify

- Rosetta for Linux inside a Lima `vz` engine running Docker amd64 images (binfmt registration in the pinned guest).
- Whether `runsc` can run amd64 binaries through Rosetta's binfmt handler (expected: no).
- Current Mattermost image architectures at the time M2 starts; the situation may change.
- Multi-architecture availability of the Playwright Chromium image and any other image the mirror itself ships (resolver, gateway, sinkhole, relay).
