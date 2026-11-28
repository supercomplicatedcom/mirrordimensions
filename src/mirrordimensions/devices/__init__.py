# SPDX-License-Identifier: Apache-2.0
"""Physical objects: sites, devices and their types (build spec, "Physical objects and
device APIs"; decision 0026).

Each type is `devices/<type>/type.yaml`: its properties, commands with their consequence
level, behaviour, telemetry and faults. The simulator in `devices/world/sim.py` runs them,
inside the world and, for replay, here.
"""

from __future__ import annotations

from functools import cache
from importlib.resources import files
from typing import Any

from ruamel.yaml import YAML

from mirrordimensions.devices.world.sim import LEVELS

PACKAGE = "mirrordimensions.devices"


@cache
def type_names() -> frozenset[str]:
    root = files(PACKAGE)
    return frozenset(
        p.name for p in root.iterdir() if p.is_dir() and p.joinpath("type.yaml").is_file()
    )


@cache
def load_type(name: str) -> dict[str, Any]:
    text = files(PACKAGE).joinpath(name, "type.yaml").read_text(encoding="utf-8")
    data: dict[str, Any] = YAML(typ="safe").load(text)  # pyright: ignore[reportUnknownMemberType]
    for command in data.get("commands", {}).values():
        if command.get("consequence") not in LEVELS:
            raise ValueError(f"{name}: every command needs a consequence: {', '.join(LEVELS)}")
    return data


def types_for(devices: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """The type definitions the given devices use, by name."""
    return {t: load_type(t) for t in sorted({d["type"] for d in devices})}
