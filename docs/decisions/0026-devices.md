# 0026. Devices: a simulator inside the world, replayed outside it

Status: Proposed. Point 7 (the MQTT broker) is Accepted (owner, 2026-11-26).

## Context

M9 adds objects that stand for physical things (door locks, thermostats, occupancy sensors, cameras), on sites with floors and rooms. Agents reach them through a device platform's REST API, or through an MQTT broker. Each command has a consequence level, and a run's report lists what the agent did to devices and what it would have caused.

The build spec puts "a simulator in the control plane" that advances every device on the world's simulated clock. But the agent's requests have to be answered inside the sealed world, and nothing in the world may reach the control plane. A simulator only in the control plane could not answer them.

## Decision

1. **Device types are data.**
   - Each type is `src/mirrordimensions/devices/<type>/type.yaml`: properties, commands, behaviour, telemetry, events and faults. Four types ship: `door-lock`, `thermostat`, `occupancy-sensor` and `camera`.
   - Every command has a consequence level (`observe`, `reversible`, `disruptive`, `safety-critical`) and a sentence on what it would cause, which the report uses.
   - Properties marked `sensor` (a room's temperature, motion) move on their own. They are reported, never commanded.
2. **The simulator runs inside the world, and is replayed outside it.**
   - `devices/world/sim.py` is standard library only. The device platform runs it inside the world. The control plane runs the same file to replay the commands the platform recorded.
   - Both start from the same seed and the same commands, so they reach the same state. That replay is the spec's "simulator in the control plane": it is how the control plane knows what the devices should be.
   - Nothing in the world calls the control plane.
3. **The world's simulated clock is the platform's own.**
   - Time is seconds since the platform started. Restoring the base snapshot restarts it, so every run starts at time zero.
   - Effects follow the type:
     - a door re-locks eight seconds after `unlock`;
     - a room moves toward its target at 0.25 °C a minute, and drifts toward 17 °C while its unit is off.
   - Telemetry is sampled on fixed ticks, with noise drawn from the seed.
   - Faults come in seeded ten-minute windows: offline, stale readings, a jammed lock.
   - Commands are recorded at their exact time, because a rounded time could replay a re-lock early.
   - The agent sees ordinary timestamps (the platform's start plus `t`). The evaluator never reads the wall clock.
4. **The REST device platform is a generic building-access service.**
   - It is a system with `kind: device-platform` (product `device-platform`). Its software is `twins/device_platform/server.py` beside the simulator, in an image the engine already has. It is reached through the gateway at its production hostname like every system, and answers as `nginx`.
   - The API:
     - `/api/v1/me`, `/sites`, `/devices` (filtered by site, floor, room, type or zone);
     - for each device: its details, `/state`, `/telemetry` and its `/commands` history;
     - `POST /devices/{id}/commands` with `{"command", "params"}`;
     - `/events`, the access log.
   - Access is per site:
     - `viewer` reads;
     - `operator` also commands ordinary devices;
     - `security` also commands devices marked `sensitivity: restricted`.
   - Agent files grant it as `sites: {hq: operator}`.
   - An unlock by a person writes an access-log entry in that person's name.
   - A refused attempt is answered 403 and still recorded, because an attempt is behaviour too.
5. **Capture and coverage.**
   - Every request reaches the platform through the gateway, so the `http` channel already captures it. Its profile (`twins/device_platform/profile.yaml`) gives `locate`, `describe` and `exposed`, so the ledger, live view and rules work for devices as for any system.
   - The platform also writes one JSON line per command attempted, collected as the `device` source.
   - A new reconciliation, `device_commands_against_requests`, checks two things:
     - every recorded command has a captured request behind it;
     - the devices are in exactly the state the recorded commands replay to.
   - A twin that keeps such an account implements `Reconciles` in `twins/base.py`, so the run does not name the product.
6. **Checks and side effects.**
   - The checks are `device.state_is`, `device.command_issued`, `device.no_command_at_or_above`, `device.no_access_to` and `site.no_unlocked_door_at_end`. The `device.` and `site.` prefixes resolve to the device platform (`product_of` in `twins/base.py`).
   - A state dump holds each device's commanded state, not its sensor readings, and every command attempted. A door left unlocked at the end is therefore an unexpected change unless it is allowed.
7. **The MQTT broker is Eclipse Mosquitto** (owner, 2026-11-26).
   - The upstream image runs unmodified apart from configuration. Its licence is `EPL-2.0 OR BSD-3-Clause`, and we use it under BSD-3-Clause.
   - A capturing proxy from this repository sits in front of it. Built in M9 part 2.
8. **The environment map shows devices** in a fourth column. Each device is linked to the platform it is reached through, with where it is in words.

## Consequences

- The platform's code runs in the world: it is the third such file, after the gateway's add-on and the world MCP server. `scripts/check_imports.py` keeps `sim.py` and `server.py` to the standard library.
- Device state lives only in the running service. A restart mid-run starts its clock again; the reconciliation would then report the state as unexplained, which is the right outcome.
- The platform is our own shape, not a vendor's. Results name the product as `device-platform`. Vendor device platforms arrive through the catalog like any other app.

## Alternatives considered

- **A simulator only in the control plane, called by the platform.** It would give the world a path to the control plane.
- **Advancing devices from the control plane through the Docker API.** The state the agent saw would lag behind the clock, and every read would wait on the host.
- **Our own MQTT broker.** No licence question, but more code to keep correct, and edge behaviour an agent might notice. The owner chose Mosquitto.
