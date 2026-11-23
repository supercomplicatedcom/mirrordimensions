# 0006. How each platform is tested with only a Mac available

Status: Accepted (owner) for Windows staying unverified until a machine exists; the rest Proposed · Date: 2026-11-22 · Milestone: M0 onward

## Context

Parity (0001) has to be proven, not claimed. The project has one physical machine: an Apple Silicon Mac (M1 Pro, 16 GB memory). There is no Linux or Windows machine. The M1 cannot run a VM inside a VM (Apple added nested virtualization with M3), so it cannot host a Windows VM that itself runs WSL2.

GitHub-hosted runners:

| Runner | Can run the engine? |
| --- | --- |
| Ubuntu x64 | Yes, in `host` mode. In `lima` mode if KVM is exposed to the runner (to verify) |
| macOS arm64 | No: no nested virtualization, so no VM inside the runner |
| Windows x64 | No: WSL2 needs nested virtualization the runner does not offer |

## Decision

**1. Test matrix**

| Suite | Linux x64 (GitHub-hosted) | macOS arm64 (GitHub-hosted) | Windows x64 (GitHub-hosted) | Owner's Mac (self-hosted) |
| --- | --- | --- | --- | --- |
| Unit, lint, type check | Every push | Every push | Every push | On demand |
| Host portability (paths, permissions, locks, line endings, golden files) | Every push | Every push | Every push | - |
| Integration, isolation, end to end, `host` engine | Every pull request | - | - | - |
| Same, `lima` engine | Every pull request, if KVM is available; otherwise nightly on a larger runner | - | - | Before merging any milestone, and on demand by label |
| Same, `wsl` engine | - | - | - | - (no machine) |

- Unit tests on all three operating systems prove the host-side code is portable and that `world.json` is byte-identical across them, which is the M3 criterion "on two machines".
- The owner's Mac is the reference for the macOS `lima` engine on arm64. It is also the main development machine, so contributors can run the full integration suite locally with `mirror engine setup` and `pytest -m integration`.

**2. The self-hosted runner is fenced off.**

- It runs under a separate macOS user account with no access to the owner's files, keychain or credentials.
- It accepts jobs only from this private repository, never from forks, and only for pull requests from members.
- Its engine is separate from the one the owner develops with (its own `LIMA_HOME` under that user).
- Disk: the owner's Mac had 22 GB free when this was written. The engine, images and snapshots will not fit alongside a second engine for the runner. Measure the footprint in M0.5, record it in `docs/platforms.md`, and free disk before enabling the runner.

**3. Windows is experimental until verified.**

- The `wsl` driver and the Windows host code are built to the spec and covered by unit tests on GitHub's Windows runners.
- Every Windows-specific item in the integration and isolation suites is written and marked `requires_wsl_engine`, so it runs the day a machine exists.
- The README, `mirror engine setup` and `mirror doctor` on Windows say "experimental: not yet verified on real hardware".
- `docs/platforms/windows-verification.md` is a checklist that turns "experimental" into "supported": run every suite on a Windows 11 x64 machine with WSL2, record versions and results, and fix what fails. Any Windows 11 x64 machine with virtualization enabled will do, including a cloud VM that offers nested virtualization.

**4. Cost.** GitHub bills macOS minutes at a higher rate than Linux for private repositories. If macOS unit jobs on every push become costly, move them to every pull request and nightly; never drop them.

## Consequences

- macOS and Linux claims are backed by CI. Windows claims are not, and the product says so.
- The milestone exit criteria for the `lima` engine depend on one person's laptop until a Linux runner with KVM or a second machine exists.

## Alternatives considered

- **Rented cloud Windows VM before each release.** Offered to the owner and declined for now; it remains the quickest path to verifying Windows.
- **Windows 11 on ARM in a VM on the Mac.** Not possible on M1 (no nested virtualization for WSL2), and it would test the wrong architecture.

## To verify

- Whether GitHub's standard hosted Ubuntu runners expose `/dev/kvm` to jobs at the time CI is set up, or whether a larger runner is needed.
- That gVisor installs and runs on the hosted Ubuntu runner image.
