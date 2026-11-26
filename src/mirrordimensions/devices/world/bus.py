# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""Devices on a message broker: each device publishes its telemetry and state, and takes
commands, on topics named for where it is (decision 0026).

    <site>/<floor>/<room>/<device>/state                retained, JSON properties
    <site>/<floor>/<room>/<device>/telemetry/<property>  {"value": .., "time": ..}
    <site>/<floor>/<room>/<device>/commands/<command>    JSON parameters, from people
    <site>/<floor>/<room>/<device>/events                each command's outcome

Standard library only, beside `sim.py` and `mqttwire.py`, on the system network. It is a
client of the broker like any building controller. Each command is written to stdout as one
JSON line, and the account the control plane reads is kept in `EXPORT`.
"""

# The simulator is imported two ways (package or sibling file), so its type is not known here.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

from __future__ import annotations

import json
import os
import select
import socket
import sys
import time
from datetime import UTC, datetime
from typing import Any

try:  # on the host (tests): the package; in the world: the files beside this one
    from mirrordimensions.devices.world import mqttwire
    from mirrordimensions.devices.world.sim import Simulator
except ImportError:  # pragma: no cover
    sys.path.insert(0, "/opt/devices")
    import mqttwire  # pyright: ignore[reportMissingImports]
    from sim import Simulator  # pyright: ignore[reportMissingImports]

CONFIG = "/etc/devices/config.json"
EXPORT = "/tmp/devices/export.json"  # noqa: S108 (inside its own container)


def topic_base(device: dict[str, Any]) -> str:
    return f"{device['at']}/{device['id']}"


class Bus:
    """The devices' side of the broker: what to publish, and what a command does."""

    def __init__(self, config: dict[str, Any], epoch: float) -> None:
        self.config = config
        self.epoch = epoch
        self.clock = {"epoch": epoch, "offsets": dict(config.get("offsets") or {})}
        self.sim = Simulator(
            config["devices"],
            config["types"],
            int(config["seed"]),
            list(config.get("people") or []),
            self.clock,
        )
        self.by_base = {topic_base(d): d for d in config["devices"]}
        self.sent: dict[str, int] = {d["id"]: 0 for d in config["devices"]}  # readings sent
        self.last_state: dict[str, str] = {}
        self.attempts = 0
        self.seq = 0

    def iso(self, t: float) -> str:
        stamp = datetime.fromtimestamp(self.epoch + t, UTC).isoformat(timespec="seconds")
        return stamp.replace("+00:00", "Z")

    def emit(self, kind: str, data: dict[str, Any]) -> None:
        self.seq += 1
        line = {"seq": self.seq, "ts": time.time(), "source": "device", "type": kind, "data": data}
        sys.stdout.write(json.dumps(line, separators=(",", ":")) + "\n")
        sys.stdout.flush()

    def command_topics(self) -> list[str]:
        return [f"{base}/commands/+" for base in sorted(self.by_base)]

    def tick(self, t: float) -> list[tuple[str, bytes, bool]]:
        """What to publish now: new telemetry readings, and any state that changed."""
        out: list[tuple[str, bytes, bool]] = []
        self.sim.advance(t)
        for base, device in sorted(self.by_base.items()):
            readings = self.sim.readings[device["id"]]
            for r in readings[self.sent[device["id"]] :]:
                body = {"value": r["value"], "time": self.iso(r["t"])}
                out.append((f"{base}/telemetry/{r['property']}", json.dumps(body).encode(), False))
            self.sent[device["id"]] = len(readings)
            if self.sim.online(device["id"], t):
                state = json.dumps(self.sim.read(device["id"], t), sort_keys=True)
                if state != self.last_state.get(base):
                    self.last_state[base] = state
                    out.append((f"{base}/state", state.encode(), True))
        return out

    def command(self, topic: str, payload: bytes, t: float) -> list[tuple[str, bytes, bool]]:
        """A command published to a device's command topic."""
        base, _, name = topic.rpartition("/commands/")
        device = self.by_base.get(base)
        if device is None or not name:
            return []
        try:
            given = json.loads(payload or b"{}")
        except ValueError:
            given = None
        params = given.get("params", given) if isinstance(given, dict) else None
        if params is None:
            record = {
                "device": device["id"],
                "command": name,
                "params": {},
                "t": t,
                "who": "",
                "status": "failed",
                "error": "invalid_request",
                "message": "Send the parameters as a JSON object.",
                "consequence": self.config["types"][device["type"]]
                .get("commands", {})
                .get(name, {})
                .get("consequence", "observe"),
            }
        else:
            record = self.sim.command(device["id"], name, params, t, "")
        self.attempts += 1
        record["attempt"] = self.attempts
        self.emit("device.command", record)
        outcome = {"command": name, "status": record["status"], "time": self.iso(t)}
        if "error" in record:
            outcome |= {"error": record["error"], "message": record.get("message", "")}
        return [(f"{base}/events", json.dumps(outcome).encode(), False), *self.tick(t)]

    def export(self, t: float) -> dict[str, Any]:
        return {
            "t": t,
            "clock": self.clock,
            "devices": self.sim.snapshot(t),
            "commands": self.sim.commands,
        }


def _write_export(bus: Bus, t: float) -> None:
    os.makedirs(os.path.dirname(EXPORT), exist_ok=True)
    tmp = EXPORT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(bus.export(t), f)
    os.replace(tmp, EXPORT)


def _serve(bus: Bus, sock: socket.socket) -> None:
    cfg = bus.config
    sock.sendall(mqttwire.connect(cfg["client_id"], cfg["username"], cfg["password"], keepalive=60))
    buffer, packet_id, last_sent = b"", 1, time.time()
    connected = False

    def send(data: bytes) -> None:
        nonlocal last_sent
        sock.sendall(data)
        last_sent = time.time()

    while True:
        t = time.time() - bus.epoch
        wait = 1.0
        ready, _, _ = select.select([sock], [], [], wait)
        if ready:
            chunk = sock.recv(65536)
            if not chunk:
                raise ConnectionError("the broker closed the connection")
            buffer += chunk
            packets, buffer = mqttwire.split(buffer)
            for p in packets:
                mqttwire.parse(p)
                if p.kind == "connack":
                    if p.fields["code"] != 0:
                        raise ConnectionError(f"refused: {p.fields['code']}")
                    connected = True
                    send(mqttwire.subscribe(packet_id, bus.command_topics()))
                    packet_id += 1
                elif p.kind == "publish":
                    if p.fields["qos"] == 1:
                        send(mqttwire.puback(p.fields["packet_id"]))
                    t = time.time() - bus.epoch
                    for topic, body, retain in bus.command(
                        p.fields["topic"], p.fields["payload"], t
                    ):
                        send(mqttwire.publish(topic, body, retain=retain))
                    _write_export(bus, t)
        if connected:
            t = time.time() - bus.epoch
            for topic, body, retain in bus.tick(t):
                send(mqttwire.publish(topic, body, retain=retain))
            _write_export(bus, t)
            if time.time() - last_sent > 30:
                send(mqttwire.pingreq())


def main() -> None:
    with open(CONFIG, encoding="utf-8") as f:
        config = json.load(f)
    bus = Bus(config, time.time())
    host, _, port = str(config["broker"]).partition(":")
    bus.emit(
        "device.started",
        {"epoch": bus.epoch, "devices": sorted(d["id"] for d in config["devices"])},
    )
    while True:
        try:
            with socket.create_connection((host, int(port or 1883)), timeout=10) as sock:
                _serve(bus, sock)
        except OSError:
            time.sleep(1)  # the broker is starting, or restarted: connect again


if __name__ == "__main__":
    main()
