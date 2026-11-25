# 0019. The engine installs updates only when asked

Status: Accepted (owner) · Date: 2026-11-24 · Milestone: follow-up to M0.5

## Context

The engine is an Ubuntu VM, and Ubuntu installs updates by itself (`unattended-upgrades`, run by the `apt-daily` timers). On the owner's Mac the engine moved from kernel 7.0.0-38 to 7.0.0-44 between two boots without anyone asking (`docs/platforms.md`, 2026-11-24). That conflicts with three things:

- Package installs belong to setup and build time. Automatic updates install whenever their timer fires, which can be during a run.
- An update to Docker or containerd restarts it, which stops every container: a run in progress, or a world that was up.
- Two runs of the same scenario could run on different kernels or gVisor versions, and nobody would have chosen that.

The engine's kernel is still the second wall between the agent and the host after the VM itself, so it must not go unpatched either.

## Decision

The owner chose on-demand updates over keeping automatic updates (outside runs only) and over rebuilding the engine to update.

1. Provisioning turns off `apt-daily.timer`, `apt-daily-upgrade.timer` and `unattended-upgrades`, sets both `APT::Periodic` switches to `0`, and holds snap refreshes. An engine that already exists gets this the next time it starts, because provisioning is re-applied when its script changes.
2. `mirror engine update [--restart]` installs the pending updates (`apt-get full-upgrade`, keeping configuration files) in the engine's own network namespace, never in a container's.
   - It refuses while any container runs in the engine, so a run or a world is never cut short. Every run and world needs the sandbox up, so this covers both.
   - It lists what it updated. If a new kernel waits for a restart, it says so; with `--restart` it stops and starts the engine.
   - It writes the date to `/var/lib/engine/updated`. The first install counts as an update. An engine provisioned before this change uses the date its packages were installed.
3. `mirror engine status` shows the date of the last update and whether a restart is due. `mirror doctor` adds a note, not a failed check, when the last update is more than 14 days old or a restart is due.
4. Each result's `platform` block records the engine's kernel, Docker and gVisor versions (as before) and now `engine_updated`.

## Consequences

- Runs on one engine use the same software until someone updates it, and each result says which.
- Security fixes wait until someone runs the command. Doctor's note after 14 days is the reminder.
- The host driver (Docker Engine on a Linux host) has no guest to update. `mirror engine update` says the host's packages are the host owner's to manage. The WSL driver is configuration only and refuses for now.

## Alternatives considered

- **Automatic updates, held while a run is going.** Safer than before, but results would still change between runs without anyone choosing it, and a world left up between runs could still be restarted.
- **No updates; rebuild the engine to update.** The most reproducible, but slow enough that it would rarely be done.

## To verify

- A kernel update with `--restart`. The first real update, on 2026-11-25, changed Docker (29.10.0 to 29.10.1), gVisor and systemd but not the kernel.
