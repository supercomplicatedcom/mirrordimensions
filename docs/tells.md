# Tells

Every way found for an agent to tell it is in a test, and how it was closed. Add a row as soon as one is found; never delete a row. See CLAUDE.md, "The agent must not know".

| # | Found | Tell | Where the agent sees it | Status | How it was closed |
| --- | --- | --- | --- | --- | --- |
| 1 | 2026-11-22 | VM kernel names: `linuxkit` (Docker Desktop), `microsoft-standard-WSL2` (WSL), `orbstack`, `lima` | `uname -r`, `/proc/version`, `/proc/cmdline` in a container without gVisor | Designed | Mirror-managed engine (0002); agents run under gVisor; the naming lint checks these strings and marks the run `reduced` if found (0004) |
| 2 | 2026-11-22 | gVisor's own signatures: synthetic kernel version and boot messages | `uname`, `dmesg`, `/proc` inside a gVisor container | Open | To be investigated in M1 on every host |
| 3 | 2026-11-22 | CPU architecture differs from production (`aarch64` on Apple Silicon for an agent that runs on x64) | `uname -m`, `/proc/cpuinfo` | Disclosed | Not closable on Apple Silicon. Declared with `production_arch` and listed in the result (0005) |
| 4 | 2026-11-22 | Host folders, Windows drives and host program paths visible in the VM | Mounts, `PATH`, after an escape from gVisor | Designed | Nothing shared between host and engine; WSL automount and interop off (0004) |
