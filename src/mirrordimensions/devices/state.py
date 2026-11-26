# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""What every system that fronts devices shares (decision 0026): the configuration its
devices are simulated from, its state dump, and that dump as side-effect objects."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mirrordimensions.devices import types_for

if TYPE_CHECKING:
    from mirrordimensions.twins.base import StateObject, TwinContext


def device_config(ctx: TwinContext) -> dict[str, Any]:
    """The seed, the sites, this system's devices and their types."""
    devices = [{k: d[k] for k in ("id", "type", "at", "sensitivity")} for d in ctx.devices]
    return {
        "seed": ctx.seed,
        "company": ctx.company,
        "sites": ctx.sites,
        "devices": devices,
        "types": types_for(devices),
    }


def dump_from(ctx: TwinContext, export: dict[str, Any]) -> dict[str, Any]:
    """Each device's commanded state (not its sensor readings, which move on their own) and
    every command attempted: the same at time zero for every fresh start."""
    types = types_for(ctx.devices)
    by_id = {d["id"]: d for d in ctx.devices}
    devices: dict[str, Any] = {}
    for device_id, state in sorted(dict(export["devices"]).items()):
        d = by_id[device_id]
        props: dict[str, Any] = types[d["type"]].get("properties", {})
        devices[device_id] = {
            "type": d["type"],
            "at": d["at"],
            "sensitivity": d.get("sensitivity", "normal"),
            "state": {
                k: v for k, v in dict(state).items() if not dict(props.get(k, {})).get("sensor")
            },
        }
    return {"devices": devices, "commands": list(export["commands"])}


def state_objects(dump: dict[str, Any]) -> list[StateObject]:
    from mirrordimensions.twins.base import StateObject

    out: list[StateObject] = []
    for device_id, d in sorted(dict(dump.get("devices") or {}).items()):
        site, floor, room = [*str(d["at"]).split("/"), "", ""][:3]
        scope = {"device": device_id, "site": site, "type": str(d["type"])}
        if floor:
            scope["floor"] = floor
        if room:
            scope["room"] = room
        out.append(StateObject(key=f"device:{device_id}", scope=scope, value=d["state"]))
    return out


def merge(dumps: list[dict[str, Any]]) -> dict[str, Any]:
    """Several systems' device dumps as one, for checks that span every device."""
    devices: dict[str, Any] = {}
    commands: list[dict[str, Any]] = []
    for dump in dumps:
        devices.update(dict(dump.get("devices") or {}))
        commands += list(dump.get("commands") or [])
    return {"devices": devices, "commands": commands}


def published_commands(
    events: list[dict[str, Any]],
    publishes: list[dict[str, Any]],
    devices: list[dict[str, Any]],
    brokers: list[Any],
) -> list[dict[str, Any]]:
    """The agent's commands over MQTT: each captured publish to a device's command topic,
    paired in order with what the devices on that broker recorded for the same command.
    One with no record never reached them: the broker's access list dropped it, as MQTT
    3.1.1 brokers do without telling the client."""
    from mirrordimensions.devices import load_type

    by_host = {str(b.hostname): str(b.id) for b in brokers}
    bases = {f"{d['at']}/{d['id']}": d for d in devices if d["platform"] in by_host.values()}
    records: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for e in events:
        if e.get("type") == "device.command":
            data: dict[str, Any] = e.get("data") or {}
            records.setdefault((str(data.get("device")), str(data.get("command"))), []).append(data)
    used: dict[tuple[str, str], int] = {}
    out: list[dict[str, Any]] = []
    for e in publishes:
        data = e.get("data") or {}
        if e.get("type") != "mqtt.publish" or data.get("host") not in by_host:
            continue
        base, sep, command = str(data.get("topic", "")).rpartition("/commands/")
        device = bases.get(base)
        if not sep or device is None:
            continue
        key = (str(device["id"]), command)
        n = used.get(key, 0)
        found = records.get(key, [])
        record = found[n] if n < len(found) else None
        used[key] = n + 1
        spec = load_type(str(device["type"])).get("commands", {}).get(command, {})
        out.append(
            {
                "device": device["id"],
                "command": command,
                "consequence": spec.get("consequence", "observe"),
                "status": record["status"] if record else "denied",
                **({"error": record["error"]} if record and "error" in record else {}),
                "event": e.get("seq"),
            }
        )
    return out
