# SPDX-License-Identifier: Apache-2.0
"""Choose the engine driver for this host, and remember the choice."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from mirrordimensions.engine.host import HostEngine
from mirrordimensions.engine.lima import LimaEngine
from mirrordimensions.engine.wsl import WslEngine
from mirrordimensions.errors import MirrorError
from mirrordimensions.hostos.dirs import data_dir
from mirrordimensions.hostos.files import write_text
from mirrordimensions.hostos.info import host_os

DriverName = Literal["lima", "wsl", "host"]
AnyEngine = LimaEngine | WslEngine | HostEngine

ALLOWED: dict[str, tuple[DriverName, ...]] = {
    "macos": ("lima",),
    "linux": ("lima", "host"),
    "windows": ("wsl",),
}


def _choice_file() -> Path:
    return data_dir() / "engine.json"


def default_driver() -> DriverName:
    system = host_os()
    if system not in ALLOWED:
        raise MirrorError(
            "This host is not supported.",
            f"No engine driver exists for {system}.",
            "See docs/platforms.md for supported hosts.",
        )
    return ALLOWED[system][0]


def chosen_driver() -> DriverName:
    path = _choice_file()
    if path.is_file():
        name = json.loads(path.read_text(encoding="utf-8")).get("driver")
        if name in ("lima", "wsl", "host"):
            return name
    return default_driver()


def remember(driver: DriverName) -> None:
    write_text(_choice_file(), json.dumps({"driver": driver}) + "\n", owner_only=True)


def get_engine(driver: DriverName | None = None) -> AnyEngine:
    name = driver or chosen_driver()
    if name not in ALLOWED.get(host_os(), ()):
        raise MirrorError(
            f"The {name} driver does not run on {host_os()}.",
            f"Drivers for this host: {', '.join(ALLOWED.get(host_os(), ())) or 'none'}.",
            "Run: mirror engine setup, without --driver, to use the default.",
        )
    if name == "lima":
        return LimaEngine()
    if name == "wsl":
        return WslEngine()
    return HostEngine()
