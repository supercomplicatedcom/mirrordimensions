# SPDX-License-Identifier: Apache-2.0
"""M9, devices tied into the company (decision 0026, points 9 to 12): badges and people's
hours, the device checks against recorded dumps, the scenarios' devices, the physical
consequences section, and protocols the mirror cannot capture."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

from mirrordimensions.config.manifest import Manifest
from mirrordimensions.devices import consequences, types_for
from mirrordimensions.devices.people import badge_holders
from mirrordimensions.devices.world.sim import DAY_S, Simulator, replay
from mirrordimensions.errors import MirrorError

FIXTURES = Path(__file__).parent.parent / "fixtures" / "devices"
DEVICES: list[dict[str, Any]] = [
    {"id": "main-entrance", "type": "door-lock", "at": "hq/f1/lobby", "sensitivity": "normal"},
    {
        "id": "server-room-door",
        "type": "door-lock",
        "at": "hq/f2/server-room",
        "sensitivity": "restricted",
    },
    {"id": "conf-b-climate", "type": "thermostat", "at": "hq/f2/conference-b"},
    {"id": "conf-b-occupancy", "type": "occupancy-sensor", "at": "hq/f2/conference-b"},
    {"id": "lobby-camera", "type": "camera", "at": "hq/f1/lobby"},
]
SITES = [
    {
        "id": "hq",
        "name": "Headquarters",
        "floors": [
            {"id": "f1", "rooms": ["lobby"]},
            {"id": "f2", "rooms": ["conference-b", "server-room"]},
        ],
    }
]
MONDAY_6AM = 1_795_413_600.0  # 2026-11-23 06:00 UTC, a Monday


def _person(pid: str, **extra: Any) -> dict[str, Any]:
    return {
        "id": pid,
        "name": pid.replace("-", " ").title(),
        "username": pid.replace("-", "."),
        "badge": f"1{len(pid):04d}",
        "site": "hq",
        "place": "hq/f2/conference-b",
        "arrive_min": 9 * 60,
        "leave_min": 17 * 60,
        "restricted": False,
        "left_ago": None,
        **extra,
    }


def _sim(people: list[dict[str, Any]], seed: int = 7) -> Simulator:
    return Simulator(DEVICES, types_for(DEVICES), seed, people, {"epoch": MONDAY_6AM})


def _first_workday(sim: Simulator, person: dict[str, Any]) -> tuple[float, float]:
    """The hours of the first day the person is in, as t."""
    for day in range(20):
        hours = sim._hours(person, sim._local("hq", day * DAY_S))  # pyright: ignore[reportPrivateUsage]
        if hours is not None:
            return hours
    raise AssertionError("never in")


# -- badges and people's hours ---------------------------------------------------------------


def test_occupancy_follows_people_and_the_same_seed_gives_the_same_day() -> None:
    people = [_person("lena-moreau"), _person("tomas-reyes")]
    sim = _sim(people)
    arrive, leave = _first_workday(sim, people[0])
    assert sim.read("conf-b-occupancy", max(arrive - 60, 0))["people"] <= 1
    assert sim.read("conf-b-occupancy", arrive + 3600)["occupied"] is True
    again = _sim(people)
    t = arrive + 3600
    assert again.read("conf-b-occupancy", t) == sim.read("conf-b-occupancy", t)
    assert sim.read("conf-b-occupancy", leave + 4 * 3600)["people"] == 0
    # A weekend: nobody in.
    saturday = 5 * DAY_S + 6 * 3600
    assert sim.read("conf-b-occupancy", saturday)["people"] == 0


def test_an_arrival_is_a_badge_at_the_door_and_the_camera_sees_who_it_matched() -> None:
    person = _person("lena-moreau", place="hq/f1/lobby")
    sim = _sim([person])
    arrive, _ = _first_workday(sim, person)
    log = sim.access_log(arrive - 1, arrive + 5)
    badge = next(e for e in log if e["type"] == "access.granted")
    assert badge["device"] == "main-entrance"  # never the restricted door
    assert badge["name"] == "Lena Moreau" and badge["badge"] == person["badge"]
    motion = next(e for e in log if e["type"] == "motion.detected")
    assert motion["device"] == "lobby-camera" and motion["badge_match"] == "Lena Moreau"
    assert sim.read("lobby-camera", arrive + 10)["motion"] is True
    assert sim.read("lobby-camera", arrive + 120)["motion"] is False


def test_a_leaver_long_gone_tries_once_within_the_week_the_log_keeps() -> None:
    leaver = _person("ines-falk", left_ago=27 * 24 * 60)
    sim = _sim([leaver])
    denied = [e for e in sim.access_log(-60 * DAY_S, 0) if e["type"] == "access.denied"]
    assert len(denied) == 1 and -5 * DAY_S <= denied[0]["t"] < 0


def test_a_leavers_badge_is_disabled_and_fails_the_one_time_it_is_tried() -> None:
    leaver = _person("ines-falk", left_ago=3 * 24 * 60)  # left three days before t = 0
    sim = _sim([leaver])
    log = sim.access_log(-10 * DAY_S, 2 * DAY_S)
    denied = [e for e in log if e["type"] == "access.denied"]
    assert len(denied) == 1 and denied[0]["reason"] == "badge_disabled"
    assert denied[0]["t"] > -3 * DAY_S
    assert all(e["t"] < -3 * DAY_S for e in log if e["type"] == "access.granted")
    assert sim.read("conf-b-occupancy", 2 * 3600 + 4 * 3600)["people"] == 0


def test_badge_holders_come_from_the_world_with_a_badge_each_and_leavers_marked() -> None:
    from mirrordimensions.world.generate import generate

    manifest = Manifest.model_validate(
        {
            "version": 1,
            "name": "hq",
            "company": {
                "name": "Northfield Logistics",
                "domain": "northfield-logistics.com",
                "seed": 11,
            },
            "apps": [
                {
                    "id": "building-access",
                    "kind": "device-platform",
                    "hostname": "access.northfield-logistics.com",
                }
            ],
            "sites": SITES,
            "devices": [dict(d, platform="building-access") for d in DEVICES],
        }
    )
    world = generate(manifest)
    holders = badge_holders(world, SITES)
    assert len(holders) == len(world.people)
    assert holders == badge_holders(world, SITES)  # the same world, the same badges
    assert len({h["badge"] for h in holders}) == len(holders)
    assert any(h["left_ago"] is not None for h in holders)
    assert all(h["place"].startswith("hq/") and 450 <= h["arrive_min"] < 600 for h in holders)


def test_the_platforms_log_and_badge_list_show_a_leavers_badge_failing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mirrordimensions.twins.device_platform import server

    leaver = _person("ines-falk", left_ago=2 * 24 * 60)
    people = [_person("lena-moreau", place="hq/f1/lobby"), leaver]
    config = {
        "seed": 7,
        "admin_token": "t",
        "company": "Northfield Logistics",
        "sites": SITES,
        "offsets": {"hq": 0},
        "devices": DEVICES,
        "types": types_for(DEVICES),
        "people": people,
    }
    monkeypatch.setattr(server.sys.stdout, "write", lambda _: 0)
    p = server.Platform(config)
    log = p.access_log(0.0)
    denied = [e for e in log if e["type"] == "access.denied"]
    assert len(denied) == 1 and denied[0]["actor"] == "Ines Falk"
    assert denied[0]["reason"] == "badge_disabled" and denied[0]["method"] == "badge"
    assert any(e["type"] == "access.granted" and e["actor"] == "Lena Moreau" for e in log)
    times = [e["time"] for e in log]
    assert times == sorted(times)
    badges = {b["holder"]: b for b in p.badges(0.0)}
    assert badges["Ines Falk"]["status"] == "disabled" and "disabled_at" in badges["Ines Falk"]
    assert badges["Lena Moreau"]["status"] == "active"


def test_replay_with_the_platforms_clock_reaches_the_same_occupancy() -> None:
    people = [_person("lena-moreau"), _person("tomas-reyes")]
    live = _sim(people)
    arrive, _ = _first_workday(live, people[0])
    live.command("conf-b-occupancy", "recalibrate", {}, arrive + 30, "a")
    t = arrive + 3600
    state = live.snapshot(t)
    again = replay(DEVICES, types_for(DEVICES), 7, live.commands, t, people, {"epoch": MONDAY_6AM})
    assert again == state and state["conf-b-occupancy"]["people"] >= 1


# -- the device checks against recorded dumps ---------------------------------------------------


def _rc(fixture: dict[str, Any]) -> Any:
    return SimpleNamespace(
        acts_as=SimpleNamespace(username=fixture["acts_as"]),
        ctx=SimpleNamespace(devices=fixture["devices"]),
        facts={"after": fixture["after"], "mqtt_commands": []},
    )


@pytest.mark.parametrize(("name", "passes"), [("passing", True), ("failing", False)])
def test_each_device_check_has_a_passing_and_a_failing_fixture(name: str, passes: bool) -> None:
    from mirrordimensions.twins.device_platform.ops import operations

    fixture = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    ops = operations()
    covered: set[str] = set()
    for check in fixture["checks"]:
        ((full, args),) = check.items()
        op = full.partition(".")[2]
        covered.add(op)
        if op in ops.event_checks:
            outcome = ops.event_checks[op](_rc(fixture), args, fixture["events"])
        else:
            outcome = ops.checks[op](_rc(fixture), args)
        assert outcome.passed is passes, (full, outcome.evidence)
        assert outcome.evidence
    assert covered == set(ops.checks) | set(ops.event_checks)  # every check, both ways


def test_an_attempt_counts_when_asked_for_even_when_it_was_refused() -> None:
    from mirrordimensions.twins.device_platform.ops import command_issued

    fixture = json.loads((FIXTURES / "passing.json").read_text(encoding="utf-8"))
    fixture["after"]["commands"].append(
        {
            "device": "server-room-door",
            "command": "unlock",
            "who": fixture["acts_as"],
            "consequence": "disruptive",
            "status": "denied",
        }
    )
    args = {"device": "server-room-door"}
    assert not command_issued(_rc(fixture), args).passed
    assert command_issued(_rc(fixture), args | {"attempted": True}).passed


# -- the scenarios' devices --------------------------------------------------------------------


def test_built_in_device_scenarios_find_their_devices_in_the_world() -> None:
    from mirrordimensions.devices import refs
    from mirrordimensions.runner import scenario

    visitor = scenario.builtin()["let-visitor-in"]
    values = refs.resolve(visitor.id, visitor.devices, DEVICES, SITES)
    assert values["entrance.id"] == "main-entrance"
    assert values["restricted.id"] == "server-room-door"
    assert values["restricted.room"] == "server room" and values["entrance.site"] == "Headquarters"
    assert scenario.SUITES["devices"] == ("let-visitor-in", "comfort-complaint")
    assert len(scenario.SUITES["core"]) == 10
    with pytest.raises(MirrorError, match="needs a restricted door-lock"):
        refs.resolve(visitor.id, visitor.devices, DEVICES[:1], SITES)


# -- physical consequences ---------------------------------------------------------------------


def test_physical_consequences_say_what_would_happen_whether_asked_for_and_asked_first() -> None:
    from mirrordimensions.runner import scenario

    visitor = scenario.builtin()["let-visitor-in"]
    values = {"entrance.id": "main-entrance", "restricted.id": "server-room-door"}
    devices = [dict(d, platform="building-access", product="device-platform") for d in DEVICES]
    attempts = [
        {"device": "main-entrance", "command": "unlock", "consequence": "disruptive",
         "status": "completed", "event": 30},
        {"device": "server-room-door", "command": "unlock", "consequence": "disruptive",
         "status": "denied", "event": 44},
        {"device": "conf-b-climate", "command": "set_target", "consequence": "reversible",
         "status": "completed", "event": 50},
    ]  # fmt: skip
    rows = consequences.section(
        attempts,
        devices,
        [scenario.render(c, values) for c in visitor.checks.success],
        [scenario.render(c, values) for c in visitor.checks.forbidden],
        [],
        delivered=10,
        said=[5, 40],
    )
    assert [(r["device"], r["called_for"], r["asked_first"]) for r in rows] == [
        ("main-entrance", True, False),  # what the job asked for, done without asking
        ("server-room-door", False, True),  # ruled out by the job; it asked, then tried
    ]
    assert rows[0]["causes"].startswith("The door unlocks for eight seconds")
    assert rows[1]["status"] == "denied" and rows[1]["asked_at"] == 40


def test_the_report_has_a_physical_consequences_section(tmp_path: Path) -> None:
    from mirrordimensions.trace import report

    row = {
        "device": "server-room-door", "where": "hq/f2/server-room", "command": "hold_open",
        "consequence": "safety-critical", "status": "completed",
        "causes": "The door stays unlocked and open until someone locks it again.",
        "called_for": False, "why": "nothing in the job asked for it", "asked_first": False,
        "event": 9,
    }  # fmt: skip
    (tmp_path / "result.json").write_text(json.dumps({"run_id": "r_abcd1", "physical": [row]}))
    page = report.render(tmp_path)
    assert 'id="physical"' in page and "stays unlocked and open" in page
    (tmp_path / "result.json").write_text(json.dumps({"run_id": "r_abcd1", "physical": []}))
    assert 'id="physical"' not in report.render(tmp_path)  # a world without devices


# -- protocols without a capturing proxy -------------------------------------------------------


def _manifest(**device: Any) -> dict[str, Any]:
    return {
        "version": 1,
        "name": "hq",
        "company": {"name": "Northfield Logistics", "domain": "northfield-logistics.com", "seed": 3},
        "apps": [
            {"id": "building-access", "kind": "device-platform",
             "hostname": "access.northfield-logistics.com"},
            {"id": "building-bus", "kind": "message-broker",
             "hostname": "mqtt.northfield-logistics.com"},
        ],
        "sites": SITES,
        "devices": [
            {"id": "main-entrance", "type": "door-lock", "at": "hq/f1/lobby",
             "platform": "building-access", **device}
        ],
    }  # fmt: skip


@pytest.mark.parametrize("protocol", ["modbus", "bacnet", "opc-ua", "rtsp"])
def test_a_device_protocol_with_no_capturing_proxy_cannot_be_declared(protocol: str) -> None:
    with pytest.raises(ValidationError, match="no capturing proxy"):
        Manifest.model_validate(_manifest(protocol=protocol))


def test_a_captured_protocol_must_match_the_system_it_is_on() -> None:
    Manifest.model_validate(_manifest(protocol="rest"))
    Manifest.model_validate(_manifest(protocol="mqtt", platform="building-bus"))
    with pytest.raises(ValidationError, match="speaks rest"):
        Manifest.model_validate(_manifest(protocol="mqtt"))


def test_mirror_validate_rejects_a_device_protocol_with_no_capturing_proxy(
    tmp_path: Path,
) -> None:
    from ruamel.yaml import YAML
    from typer.testing import CliRunner

    from mirrordimensions.cli.app import app

    yaml = YAML()
    with (tmp_path / "mirror.yaml").open("w", encoding="utf-8") as f:
        yaml.dump(_manifest(protocol="bacnet"), f)  # pyright: ignore[reportUnknownMemberType]
    out = CliRunner().invoke(app, ["--project", str(tmp_path), "validate"])
    assert out.exit_code == 1, out.output  # a file that fails validation
    assert "no capturing proxy" in out.output


def test_a_run_whose_record_lacks_the_systems_own_commands_is_unexplained() -> None:
    from mirrordimensions.devices import reconcile

    export = {"commands": [{"device": "main-entrance"}, {"device": "server-room-door"}]}
    one = {"type": "device.command", "data": {"platform": "building-access", "device": "x"}}
    assert reconcile.account_collected([one, one], "building-access", export) == []
    found = reconcile.account_collected([], "building-access", export)
    assert found == ["building-access: recorded 2 command attempt(s), 0 reached the run's record"]


def test_a_finished_runs_record_takes_nothing_from_the_next_run(tmp_path: Path) -> None:
    from mirrordimensions.network.events import Collector

    collector = Collector(None, tmp_path / "events.jsonl", {}, 0.0)  # type: ignore[arg-type]
    collector.emit("runner", "run.end", {"status": "passed"})
    collector.close()
    collector.emit("runner", "work.delivered", {})  # the next scenario in the suite
    lines = (tmp_path / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(x)["type"] for x in lines] == ["run.end"]
