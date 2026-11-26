# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""The device simulator: every device's state on the world's simulated clock.

Standard library only. The device platform runs this file inside the world, and the control
plane runs the same file to replay what was captured (decision 0026), so both reach the same
state from the same seed and the same commands:

- time is seconds since the platform started (`t`), never the wall clock;
- a command's effect applies at once; a delayed part (`after_s`, `then`) applies at its time;
- a property can move toward a target at a set rate (a room's temperature);
- telemetry is sampled on fixed ticks, with seeded noise;
- faults (offline, stale readings, a jammed lock) come in seeded windows and replay exactly.
"""

from __future__ import annotations

import hashlib
import math
from typing import Any

LEVELS = ("observe", "reversible", "disruptive", "safety-critical")
FAULT_WINDOW_S = 600.0
FAULT_CHANCE = {"offline": 0.05, "stale": 0.05, "jammed": 0.04}


def draw(seed: int, *parts: object) -> float:
    """A number in [0, 1) fixed by the seed and the labels: the simulator's only randomness."""
    text = ":".join([str(seed), *(str(p) for p in parts)])
    return int.from_bytes(hashlib.sha256(text.encode()).digest()[:8], "big") / 2.0**64


def level_at_least(level: str, floor: str) -> bool:
    return LEVELS.index(level) >= LEVELS.index(floor)


class CommandError(Exception):
    """A command the device refused or could not carry out; `reason` is a short code."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message


class Simulator:
    """All devices of one platform. Time only moves forward; `advance` runs every timer,
    rate and telemetry tick up to the time asked for, in order."""

    def __init__(self, devices: list[dict[str, Any]], types: dict[str, dict[str, Any]], seed: int):
        self.seed = seed
        self.types = types
        self.devices = {d["id"]: d for d in devices}
        self.t = 0.0
        self.state: dict[str, dict[str, Any]] = {}
        self.reported: dict[str, dict[str, Any]] = {}  # last telemetry value, for stale faults
        self.timers: list[tuple[float, int, str, dict[str, Any]]] = []
        self.readings: dict[str, list[dict[str, Any]]] = {}
        self.commands: list[dict[str, Any]] = []
        self._n = 0
        for d in devices:
            spec = types[d["type"]]
            self.state[d["id"]] = {
                name: prop.get("default") for name, prop in spec.get("properties", {}).items()
            }
            self.reported[d["id"]] = {}
            self.readings[d["id"]] = []

    # -- faults ---------------------------------------------------------------------------

    def fault(self, device: str, kind: str, t: float) -> bool:
        """Whether a fault of this kind is active on the device at time t."""
        spec = self.types[self.devices[device]["type"]]
        if kind not in spec.get("faults", []):
            return False
        window = math.floor(t / FAULT_WINDOW_S)
        if draw(self.seed, "fault", kind, device, window) >= FAULT_CHANCE.get(kind, 0.0):
            return False
        start = window * FAULT_WINDOW_S + draw(self.seed, "start", kind, device, window) * 480
        length = 30 + draw(self.seed, "length", kind, device, window) * 90
        return start <= t < start + length

    def online(self, device: str, t: float) -> bool:
        return not self.fault(device, "offline", t)

    # -- time -----------------------------------------------------------------------------

    def _ticks(self, device: str) -> list[dict[str, Any]]:
        return list(self.types[self.devices[device]["type"]].get("telemetry", []))

    def _next_tick(self, after: float) -> float:
        nxt = math.inf
        for device in self.devices:
            for tel in self._ticks(device):
                every = float(tel["every_s"])
                nxt = min(nxt, (math.floor(after / every) + 1) * every)
        return nxt

    def _rates(self, upto: float) -> None:
        """Move rate-driven properties from self.t to `upto`."""
        dt = upto - self.t
        if dt <= 0:
            return
        for device, state in self.state.items():
            spec = self.types[self.devices[device]["type"]]
            for rule in spec.get("behavior", []):
                if not _applies(rule, state):
                    continue
                prop = rule["property"]
                toward = rule["toward"]
                goal = float(state[toward] if isinstance(toward, str) else toward)
                now = float(state[prop])
                step = float(rule["rate_per_min"]) * dt / 60.0
                state[prop] = (
                    goal if abs(goal - now) <= step else now + math.copysign(step, goal - now)
                )

    def _sample(self, at: float) -> None:
        for device in self.devices:
            for tel in self._ticks(device):
                every = float(tel["every_s"])
                if abs(at / every - round(at / every)) > 1e-9:
                    continue
                prop = tel["property"]
                if not self.online(device, at):
                    continue
                if self.fault(device, "stale", at) and prop in self.reported[device]:
                    value = self.reported[device][prop]
                else:
                    value = self.state[device][prop]
                    noise = float(tel.get("noise", 0.0))
                    if noise and isinstance(value, (int, float)) and not isinstance(value, bool):
                        tick = round(at / every)
                        value = (
                            value + (draw(self.seed, "noise", device, prop, tick) - 0.5) * 2 * noise
                        )
                    value = _round(value)
                    self.reported[device][prop] = value
                self.readings[device].append({"t": _round(at), "property": prop, "value": value})

    def advance(self, t: float) -> None:
        while True:
            timer = self.timers[0][0] if self.timers else math.inf
            tick = self._next_tick(self.t)
            nxt = min(timer, tick)
            if nxt > t:
                break
            self._rates(nxt)
            self.t = nxt
            while self.timers and self.timers[0][0] <= nxt:
                _, _, device, values = self.timers.pop(0)
                self.state[device].update(values)
            if tick == nxt:
                self._sample(nxt)
        self._rates(t)
        self.t = max(self.t, t)

    # -- reading and commanding -----------------------------------------------------------

    def read(self, device: str, t: float) -> dict[str, Any]:
        """What the device reports at t: its properties, or the last ones seen while offline."""
        self.advance(t)
        state = {k: _round(v) for k, v in self.state[device].items()}
        stale = self.fault(device, "stale", t)
        for prop, value in self.reported[device].items():
            if stale:
                state[prop] = value
        return state

    def command(
        self, device: str, name: str, params: dict[str, Any], t: float, who: str
    ) -> dict[str, Any]:
        """Carry out a command at t, or refuse it. Every attempt is recorded."""
        self.advance(t)
        self._n += 1
        spec = self.types[self.devices[device]["type"]]
        record: dict[str, Any] = {
            "n": self._n,
            "device": device,
            "command": name,
            "params": params,
            "t": t,  # exact: replay must act at the very same moment
            "who": who,
            "consequence": spec.get("commands", {}).get(name, {}).get("consequence", "observe"),
        }
        try:
            command = spec.get("commands", {}).get(name)
            if command is None:
                raise CommandError(
                    "unknown_command",
                    f"{name} is not a command of this device. Commands: "
                    + ", ".join(sorted(spec.get("commands", {}))),
                )
            values = _params(command.get("params", {}), params)
            if not self.online(device, t):
                raise CommandError("offline", "The device is not responding.")
            if self.fault(device, "jammed", t) and name != "lock":
                raise CommandError("jammed", "The device reported a mechanical fault.")
            effect = command.get("effect", {})
            self.state[device].update(_fill(effect.get("set", {}), values))
            if "after_s" in effect:
                when = t + float(effect["after_s"])
                self.timers.append((when, self._n, device, _fill(effect["then"]["set"], values)))
                self.timers.sort(key=lambda x: (x[0], x[1]))
            record["status"] = "completed"
        except CommandError as err:
            record["status"] = "failed"
            record["error"] = err.reason
            record["message"] = err.message
        self.commands.append(record)
        return record

    def telemetry(self, device: str, since: float, until: float) -> list[dict[str, Any]]:
        self.advance(until)
        return [r for r in self.readings[device] if since <= r["t"] <= until]

    def snapshot(self, t: float) -> dict[str, dict[str, Any]]:
        """Every device's true state at t, for state dumps and replay."""
        self.advance(t)
        return {d: {k: _round(v) for k, v in s.items()} for d, s in sorted(self.state.items())}


def replay(
    devices: list[dict[str, Any]],
    types: dict[str, dict[str, Any]],
    seed: int,
    commands: list[dict[str, Any]],
    until: float,
) -> dict[str, dict[str, Any]]:
    """The state a platform reaches from its captured commands: what the control plane
    compares with the platform's own dump."""
    sim = Simulator(devices, types, seed)
    for c in sorted(commands, key=lambda c: (c["t"], c.get("n", 0))):
        sim.command(
            c["device"], c["command"], c.get("params") or {}, float(c["t"]), c.get("who", "")
        )
    return sim.snapshot(until)


def _applies(rule: dict[str, Any], state: dict[str, Any]) -> bool:
    when: dict[str, Any] = rule.get("when") or {}
    unless: dict[str, Any] = rule.get("unless") or {}
    return all(state.get(k) == v for k, v in when.items()) and not (
        unless and all(state.get(k) == v for k, v in unless.items())
    )


def _params(spec: dict[str, Any], given: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, rule in spec.items():
        if name not in given:
            raise CommandError("missing_parameter", f"The command needs {name}.")
        value = given[name]
        if rule.get("type") == "number":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise CommandError("invalid_parameter", f"{name} must be a number.")
            low, high = rule.get("min"), rule.get("max")
            if (low is not None and value < low) or (high is not None and value > high):
                raise CommandError("invalid_parameter", f"{name} must be between {low} and {high}.")
            value = float(value)
        elif rule.get("type") == "enum" and value not in rule.get("values", []):
            raise CommandError(
                "invalid_parameter", f"{name} must be one of: {', '.join(rule['values'])}."
            )
        out[name] = value
    extra = sorted(set(given) - set(spec))
    if extra:
        raise CommandError("invalid_parameter", f"Unexpected parameter: {', '.join(extra)}.")
    return out


def _fill(values: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    return {
        k: params[v[1:]] if isinstance(v, str) and v.startswith("$") else v
        for k, v in values.items()
    }


def _round(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 2)
    return value
