# Windows verification checklist

Windows 11 x64 support is **experimental** until every item below has passed on a real Windows machine and been recorded in `docs/platforms.md`. Any Windows 11 x64 machine with hardware virtualization will do, including a cloud VM with nested virtualization. See decision 0006.

## Machine

- [ ] Windows 11 edition and build, WSL version, WSL networking mode (NAT or mirrored), CPU, memory, free disk recorded

## Install and engine

- [ ] `uv tool install` of the package and `mirror --help` work in PowerShell and Windows Terminal
- [ ] `mirror engine setup` imports the engine distribution and installs Docker Engine and gVisor
- [ ] `mirror engine status` shows driver `wsl`, boundary `shared-vm`, pinned versions and resources
- [ ] The engine stays running for a 30-minute run with no other WSL activity
- [ ] `mirror engine destroy` removes the distribution and every file it created

## Hardening (0004)

- [ ] No Windows drive or `/mnt/wsl` is visible inside the engine
- [ ] Windows programs cannot be run from the engine (interop off)
- [ ] The Windows `PATH` is not in the engine's environment
- [ ] A listener on Windows `127.0.0.1` cannot be reached from the agent network or the system network, in NAT and mirrored modes
- [ ] The Docker endpoint refuses connections without the client certificate
- [ ] The client key file's ACL grants only the current user

## Isolation and coverage

- [ ] `runsc` runs an agent container under WSL2 (if not: record it, and Windows stays at `reduced`)
- [ ] The full egress suite, inside-out suite and naming lint pass
- [ ] `mirror doctor` reports `full`
- [ ] Event delay from gateway to host within two seconds

## Host code

- [ ] A project in a folder with spaces and non-ASCII characters works
- [ ] Owner-only ACLs are applied to `.mirror/ca/`, `.mirror/import/` and the host data folder
- [ ] Ctrl+C during `mirror run` ends the run cleanly with a result marked `stopped`
- [ ] The host stays awake during a run; a forced sleep produces `errored`, reason `host slept`
- [ ] `world.json` for the golden seed is byte-identical to the committed golden file

## End to end

- [ ] `mirror init`, `mirror build`, `mirror run core --agent scripted-good` produce the same `result.json` as on Linux, apart from ids, timestamps and the `platform` block
