# SPDX-License-Identifier: Apache-2.0
"""Device coverage: what a device platform did is explained by what was captured
(decision 0026; CLAUDE.md, "a new way to touch something has a reconciliation test").

- Every command the platform recorded arrived through the gateway: a captured request to
  that device's command endpoint stands behind it.
- The platform's devices are in exactly the state its recorded commands produce, replayed
  here with the same simulator: nothing changed them by another route.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any, cast

from mirrordimensions.devices.world.sim import replay

_COMMAND_PATH = re.compile(r"^/api/v1/devices/([^/?]+)/commands(?:\?.*)?$")


def _data(event: dict[str, Any]) -> dict[str, Any]:
    return cast(dict[str, Any], event.get("data") or {})


def account_collected(
    events: list[dict[str, Any]], platform: str, export: dict[str, Any]
) -> list[str]:
    """The run's record holds every command attempt the system itself counts: otherwise the
    checks below would have nothing to explain, and pass."""
    collected = sum(
        1
        for e in events
        if e.get("type") == "device.command" and _data(e).get("platform") == platform
    )
    recorded = len(export.get("commands") or [])
    if collected == recorded:
        return []
    return [
        f"{platform}: recorded {recorded} command attempt(s), {collected} reached the run's record"
    ]


def commands_against_requests(
    events: list[dict[str, Any]], hostname: str, platform: str
) -> list[str]:
    """Commands the platform recorded with no captured request to carry them."""
    posts: Counter[str] = Counter()
    for e in events:
        d = _data(e)
        if e.get("type") != "http.exchange" or d.get("method") != "POST":
            continue
        if str(d.get("host", "")).split(":")[0] != hostname:
            continue
        match = _COMMAND_PATH.match(str(d.get("path", "")))
        if match:
            posts[match.group(1)] += 1
    attempts: Counter[str] = Counter(
        str(e["data"]["device"])
        for e in events
        if e.get("type") == "device.command" and _data(e).get("platform") == platform
    )
    return [
        f"{device}: {n} command(s) recorded, {posts[device]} request(s) captured"
        for device, n in sorted(attempts.items())
        if n > posts[device]
    ]


def state_against_commands(
    events: list[dict[str, Any]],
    platform: str,
    config: dict[str, Any],
    export: dict[str, Any],
) -> list[str]:
    """Devices whose state the recorded commands do not explain."""
    commands: list[dict[str, Any]] = [
        e["data"]
        for e in events
        if e.get("type") == "device.command"
        and _data(e).get("platform") == platform
        and _data(e).get("status") != "denied"
    ]
    found: dict[str, Any] = export["devices"]
    expected = replay(
        config["devices"],
        config["types"],
        int(config["seed"]),
        commands,
        float(export["t"]),
        list(config.get("people") or []),
        dict(export.get("clock") or {}),  # the platform's own start, which occupancy follows
    )
    return [
        f"{device}: is {found.get(device)}, its commands give {state}"
        for device, state in sorted(expected.items())
        if found.get(device) != state
    ]


def commands_against_publishes(
    events: list[dict[str, Any]], hostname: str, broker: str, bases: dict[str, str]
) -> list[str]:
    """Commands the devices on a broker carried out with no captured publish behind them.
    `bases` maps each device's topic base to its id."""
    publishes: Counter[str] = Counter()
    for e in events:
        d = _data(e)
        if e.get("type") != "mqtt.publish" or d.get("direction") != "in":
            continue
        if str(d.get("host", "")) != hostname:
            continue
        base, sep, _ = str(d.get("topic", "")).rpartition("/commands/")
        if sep and base in bases:
            publishes[bases[base]] += 1
    attempts: Counter[str] = Counter(
        str(_data(e)["device"])
        for e in events
        if e.get("type") == "device.command" and _data(e).get("platform") == broker
    )
    return [
        f"{device}: {n} command(s) carried out, {publishes[device]} publish(es) captured"
        for device, n in sorted(attempts.items())
        if n > publishes[device]
    ]
