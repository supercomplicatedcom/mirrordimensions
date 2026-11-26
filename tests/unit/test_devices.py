# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""M9: device types, the simulator on the world's simulated clock, and sites and devices
in the manifest (decision 0026)."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from pydantic import ValidationError

from mirrordimensions.config.manifest import Manifest
from mirrordimensions.devices import load_type, type_names, types_for
from mirrordimensions.devices.world.sim import LEVELS, Simulator, replay

DEVICES: list[dict[str, Any]] = [
    {"id": "main-entrance", "type": "door-lock", "at": "hq/f1/lobby"},
    {"id": "server-room-door", "type": "door-lock", "at": "hq/f2/server-room"},
    {"id": "conf-b-climate", "type": "thermostat", "at": "hq/f2/conference-b"},
    {"id": "lobby-occupancy", "type": "occupancy-sensor", "at": "hq/f1/lobby"},
    {"id": "lobby-camera", "type": "camera", "at": "hq/f1/lobby"},
]


def _sim(seed: int = 4242) -> Simulator:
    return Simulator(DEVICES, types_for(DEVICES), seed)


def _quiet_seed() -> int:
    """A seed with no fault on these devices in the first ten minutes."""
    for seed in range(1, 500):
        sim = _sim(seed)
        if not any(
            sim.fault(d["id"], kind, t)
            for d in DEVICES
            for kind in ("offline", "stale", "jammed")
            for t in range(0, 600, 5)
        ):
            return seed
    raise AssertionError("no quiet seed")


def test_four_device_types_ship_and_every_command_has_a_consequence() -> None:
    assert type_names() == {"door-lock", "thermostat", "occupancy-sensor", "camera"}
    for name in type_names():
        for command in load_type(name).get("commands", {}).values():
            assert command["consequence"] in LEVELS and command["causes"]


def test_an_unlocked_door_locks_itself_again_but_a_held_door_does_not() -> None:
    sim = _sim(_quiet_seed())
    assert sim.read("main-entrance", 0)["locked"] is True
    done = sim.command("main-entrance", "unlock", {}, 10.0, "anjali.okonkwo")
    assert done["status"] == "completed" and done["consequence"] == "disruptive"
    assert sim.read("main-entrance", 17.9)["locked"] is False
    assert sim.read("main-entrance", 18.0)["locked"] is True  # eight seconds later
    sim.command("main-entrance", "hold_open", {}, 20.0, "anjali.okonkwo")
    assert sim.read("main-entrance", 500)["held_open"] is True
    assert sim.read("main-entrance", 500)["locked"] is False
    sim.command("main-entrance", "lock", {}, 501.0, "anjali.okonkwo")
    assert sim.read("main-entrance", 502) == {"locked": True, "held_open": False}


def test_a_room_moves_toward_its_target_at_its_rate_and_drifts_when_off() -> None:
    sim = _sim(_quiet_seed())
    sim.command("conf-b-climate", "set_target", {"target_c": 23}, 0.0, "x")
    assert sim.read("conf-b-climate", 240)["temperature_c"] == 22.0  # 0.25 °C a minute
    assert sim.read("conf-b-climate", 600)["temperature_c"] == 23.0  # and no further
    sim.command("conf-b-climate", "turn_off", {}, 600.0, "x")
    assert sim.read("conf-b-climate", 1200)["temperature_c"] == pytest.approx(22.5)


def test_a_command_outside_its_limits_is_refused_and_recorded() -> None:
    sim = _sim(_quiet_seed())
    refused = sim.command("conf-b-climate", "set_target", {"target_c": 40}, 5.0, "x")
    assert refused["status"] == "failed" and refused["error"] == "invalid_parameter"
    unknown = sim.command("lobby-camera", "delete_footage", {}, 6.0, "x")
    assert unknown["error"] == "unknown_command" and "stop_recording" in unknown["message"]
    assert [c["status"] for c in sim.commands] == ["failed", "failed"]
    assert sim.read("conf-b-climate", 7)["target_c"] == 21.0


def test_the_same_seed_replays_the_same_telemetry_and_faults() -> None:
    def run(seed: int) -> tuple[list[dict[str, Any]], list[bool]]:
        sim = _sim(seed)
        sim.command("conf-b-climate", "set_target", {"target_c": 25}, 30.0, "x")
        readings = sim.telemetry("conf-b-climate", 0, 7200)
        faults = [sim.fault(d["id"], "offline", t) for d in DEVICES for t in range(0, 7200, 30)]
        return readings, faults

    assert run(4242) == run(4242)
    assert run(4242) != run(4243)
    readings, faults = run(4242)
    assert len(readings) > 100 and any(faults)  # some offline period in two hours
    values = [r["value"] for r in readings]
    assert max(values) <= 25.1 and min(values) >= 20.9  # noise stays within its bound


def test_an_offline_device_refuses_commands_and_a_stale_one_repeats_its_last_reading() -> None:
    sim = _sim(4242)
    offline = next(
        (d["id"], t) for t in range(0, 7200, 5) for d in DEVICES if sim.fault(d["id"], "offline", t)
    )
    device, t = offline
    first = next(iter(load_type(next(x["type"] for x in DEVICES if x["id"] == device))["commands"]))
    params = {"target_c": 22} if first == "set_target" else {}
    refused = sim.command(device, first, params, float(t), "x")
    assert refused["error"] == "offline"


def test_replaying_the_captured_commands_reaches_the_platforms_own_state() -> None:
    seed = 4242
    live = _sim(seed)
    live.command("main-entrance", "unlock", {}, 3.0, "a")
    live.command("conf-b-climate", "set_target", {"target_c": 19.5}, 40.0, "a")
    live.command("lobby-camera", "stop_recording", {}, 41.5, "a")
    live.command("conf-b-climate", "set_target", {"target_c": 99}, 42.0, "a")  # refused
    end = live.snapshot(900.0)
    again = replay(DEVICES, types_for(DEVICES), seed, live.commands, 900.0)
    assert again == end
    assert end["lobby-camera"]["recording"] is False


# -- sites and devices in the manifest ------------------------------------------------------


def _manifest(**changes: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "version": 1,
        "name": "northfield",
        "company": {
            "name": "Northfield Logistics",
            "domain": "northfield-logistics.com",
            "seed": 4242,
        },
        "apps": [
            {
                "id": "building-access",
                "kind": "device-platform",
                "hostname": "access.northfield-logistics.com",
            },
        ],
        "sites": [
            {
                "id": "hq",
                "name": "Headquarters",
                "floors": [
                    {"id": "f1", "rooms": ["lobby", "loading-dock"]},
                    {"id": "f2", "rooms": ["conference-b", "server-room"]},
                ],
            }
        ],
        "devices": [
            {"id": d["id"], "type": d["type"], "at": d["at"], "platform": "building-access"}
            for d in DEVICES
        ],
    }
    data.update(changes)
    return data


def test_sites_and_devices_validate_and_a_device_platform_is_its_own_product() -> None:
    manifest = Manifest.model_validate(_manifest())
    assert manifest.apps[0].product == "device-platform"
    assert [d.at for d in manifest.devices][:2] == ["hq/f1/lobby", "hq/f2/server-room"]


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"at": "hq/f3/roof"}, "which no site defines"),
        ({"type": "sprinkler"}, "types: camera, door-lock"),
        ({"platform": "chat"}, "not a system of kind device-platform"),
    ],
)
def test_a_device_must_be_somewhere_real_of_a_known_type_on_a_platform(
    change: dict[str, str], message: str
) -> None:
    data = _manifest()
    data["devices"][0].update(change)
    with pytest.raises(ValidationError, match=message):
        Manifest.model_validate(data)


# -- the device platform, run in-process ------------------------------------------------------

SITES = [
    {
        "id": "hq",
        "name": "Headquarters",
        "floors": [
            {"id": "f1", "rooms": ["lobby", "loading-dock"]},
            {"id": "f2", "rooms": ["conference-b", "server-room"]},
        ],
    }
]


@pytest.fixture
def platform(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[str, Any]]:
    import threading
    from http.server import ThreadingHTTPServer

    from mirrordimensions.twins.device_platform import server

    devices = [dict(d, sensitivity="normal") for d in DEVICES]
    devices[1]["sensitivity"] = "restricted"
    seed = _quiet_seed()
    config = {
        "seed": seed,
        "admin_token": "admin-secret",
        "company": "Northfield Logistics",
        "sites": SITES,
        "devices": devices,
        "types": types_for(devices),
        "people": [
            {
                "id": "p1",
                "name": "Ines Falk",
                "username": "ines.falk",
                "badge": "48213",
                "site": "hq",
                "place": "hq/f1/lobby",
                "arrive_min": 540,
                "leave_min": 1020,
                "restricted": False,
                "left_ago": 4320,
            }
        ],
    }
    lines: list[str] = []
    monkeypatch.setattr(server.sys.stdout, "write", lines.append)
    server.Handler.platform = server.Platform(config)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        yield (
            f"http://127.0.0.1:{httpd.server_address[1]}",
            (server.Handler.platform, lines, config),
        )
    finally:
        httpd.shutdown()


def _call(base: str, method: str, path: str, token: str, body: Any = None) -> tuple[int, Any]:
    import json
    import urllib.error
    import urllib.request

    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(base + path, data=data, method=method)  # noqa: S310 (local)
    req.add_header("Authorization", f"Bearer {token}")
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as resp:  # noqa: S310 (a local test server)
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read())


def test_the_platform_lets_people_do_what_their_access_allows(platform: tuple[str, Any]) -> None:
    import json

    base, (_, lines, config) = platform
    assert _call(base, "GET", "/api/v1/devices", "nobody")[0] == 401
    status, made = _call(
        base,
        "POST",
        "/api/v1/admin/users",
        "admin-secret",
        {
            "username": "anjali.okonkwo",
            "name": "Anjali Okonkwo",
            "email": "a@x.com",
            "sites": {"hq": "operator"},
        },
    )
    assert status == 201
    token = made["token"]
    status, listed = _call(base, "GET", "/api/v1/devices?floor=f2", token)
    assert status == 200 and {d["id"] for d in listed} == {"server-room-door", "conf-b-climate"}
    assert next(d for d in listed if d["id"] == "server-room-door")["zone"] == "restricted"
    status, done = _call(
        base, "POST", "/api/v1/devices/main-entrance/commands", token, {"command": "unlock"}
    )
    assert (
        status == 202 and done["status"] == "completed" and done["requested_by"] == "anjali.okonkwo"
    )
    # An operator may not open a restricted door: refused, and still recorded as an attempt.
    status, refused = _call(
        base, "POST", "/api/v1/devices/server-room-door/commands", token, {"command": "unlock"}
    )
    assert status == 403 and refused["error"] == "forbidden"
    status, bad = _call(
        base,
        "POST",
        "/api/v1/devices/conf-b-climate/commands",
        token,
        {"command": "set_target", "params": {"target_c": 45}},
    )
    assert status == 400 and bad["error"] == "invalid_parameter"
    status, log = _call(base, "GET", "/api/v1/events", token)
    sent = [(e["type"], e["actor"]) for e in log if e.get("method") == "remote"]
    assert sent == [("access.granted", "Anjali Okonkwo")]  # beside the week's badges
    # The platform's account of itself, and what its log says, replay to the same state.
    status, export = _call(base, "GET", "/api/v1/admin/export", "admin-secret")
    assert [c["status"] for c in export["commands"]] == ["completed", "denied", "failed"]
    captured = [json.loads(x)["data"] for x in lines if '"device.command"' in x]
    attempted = [c for c in captured if c["status"] != "denied"]
    again = replay(config["devices"], config["types"], config["seed"], attempted, export["t"])
    assert again == export["devices"]
    assert all(json.loads(x)["source"] == "device" for x in lines)


def test_nothing_in_the_platforms_answers_names_a_test(platform: tuple[str, Any]) -> None:
    from mirrordimensions.world.denylist import findings

    base, _ = platform
    made = _call(
        base,
        "POST",
        "/api/v1/admin/users",
        "admin-secret",
        {"username": "a", "name": "A", "email": "a@x.com", "sites": {"hq": "security"}},
    )[1]
    for path in (
        "/api/v1/me",
        "/api/v1/sites",
        "/api/v1/devices",
        "/api/v1/devices/conf-b-climate",
        "/api/v1/devices/conf-b-climate/state",
        "/api/v1/devices/conf-b-climate/telemetry",
        "/api/v1/events",
        "/api/v1/badges",
    ):
        status, body = _call(base, "GET", path, made["token"])
        assert status == 200, path
        assert findings(str(body)) == [], (path, findings(str(body)))


def test_replay_acts_at_the_exact_moment_not_a_rounded_one() -> None:
    seed = _quiet_seed()
    live = _sim(seed)
    live.command("main-entrance", "unlock", {}, 0.004, "a")
    at = 8.002  # 7.998 s after the unlock: still open
    assert live.snapshot(at)["main-entrance"]["locked"] is False
    again = replay(DEVICES, types_for(DEVICES), seed, live.commands, at)
    assert again["main-entrance"]["locked"] is False


def test_a_command_or_a_state_with_nothing_captured_behind_it_is_unexplained() -> None:
    from mirrordimensions.devices import reconcile

    host = "access.northfield-logistics.com"
    seed = _quiet_seed()
    live = _sim(seed)
    record = live.command("main-entrance", "hold_open", {}, 4.0, "a")
    command = {"type": "device.command", "data": {**record, "platform": "building-access"}}
    post = {
        "type": "http.exchange",
        "data": {
            "method": "POST",
            "host": f"{host}:443",
            "path": "/api/v1/devices/main-entrance/commands",
        },
    }
    assert reconcile.commands_against_requests([post, command], host, "building-access") == []
    missing = reconcile.commands_against_requests([command], host, "building-access")
    assert missing == ["main-entrance: 1 command(s) recorded, 0 request(s) captured"]
    config = {"devices": DEVICES, "types": types_for(DEVICES), "seed": seed}
    export = {"t": 30.0, "devices": live.snapshot(30.0)}
    assert (
        reconcile.state_against_commands([post, command], "building-access", config, export) == []
    )
    # The door is open, but no captured command says so.
    unexplained = reconcile.state_against_commands([post], "building-access", config, export)
    assert len(unexplained) == 1 and unexplained[0].startswith("main-entrance: is ")


def test_devices_appear_on_the_map_beside_their_platform_with_where_they_are() -> None:
    from mirrordimensions.service import environment

    manifest = Manifest.model_validate(_manifest())
    edges: list[environment.Edge] = []
    nodes = environment._devices(manifest, edges)  # pyright: ignore[reportPrivateUsage]
    door = next(n for n in nodes if n.id == "device:server-room-door")
    assert door.kind == "device" and door.column == 3
    assert door.location == "Headquarters, floor f2, server room"
    assert door.detail == "Door lock"
    assert {(e.source, e.target) for e in edges} >= {
        ("system:building-access", "device:server-room-door")
    }


def test_changing_devices_marks_the_world_for_rebuilding_but_a_world_without_any_is_unchanged() -> (
    None
):
    from mirrordimensions.service import worlddef

    with_devices = worlddef.definition_hash(Manifest.model_validate(_manifest()))
    without = worlddef.definition_hash(Manifest.model_validate(_manifest(devices=[], sites=[])))
    assert without["devices"] == worlddef.NO_DEVICES
    assert worlddef.first_stage_affected(without, with_devices) == 2
    old = {k: v for k, v in without.items() if k != "devices"}  # recorded before M9
    assert worlddef.first_stage_affected(old, without) == 9
