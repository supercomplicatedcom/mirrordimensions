# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""Engine service functions (host-level, not per project)."""

from __future__ import annotations

from collections.abc import Callable

from mirrordimensions.engine.base import EngineStatus, Resources
from mirrordimensions.engine.checks import CheckResult, run_checks
from mirrordimensions.engine.lima import LimaEngine, default_resources
from mirrordimensions.engine.registry import DriverName, get_engine, remember
from mirrordimensions.engine.wsl import WslEngine
from mirrordimensions.errors import MirrorError
from mirrordimensions.hostos.awake import keep_awake

StepFn = Callable[[str], None] | None


def setup_engine(
    resources: Resources | None = None,
    driver: DriverName | None = None,
    on_step: StepFn = None,
    experimental: bool = False,
) -> EngineStatus:
    engine = get_engine(driver)
    with keep_awake("Setting up the engine"):
        if isinstance(engine, WslEngine):
            status = engine.setup(
                resources or default_resources(), on_step, experimental=experimental
            )
        else:
            status = engine.setup(resources or default_resources(), on_step)
    remember(engine.name)  # type: ignore[arg-type]
    return status


def engine_status() -> EngineStatus:
    return get_engine().status()


def start_engine(on_step: StepFn = None) -> EngineStatus:
    return get_engine().start(on_step)


def stop_engine() -> None:
    get_engine().stop()


def destroy_engine() -> None:
    get_engine().destroy()


def check_engine() -> list[CheckResult]:
    engine = get_engine()
    if not isinstance(engine, LimaEngine):
        raise MirrorError(
            f"Engine checks are not yet available for the {engine.name} driver.",
            "M0.5 checks are implemented for the lima driver first.",
            "Track progress in docs/platforms.md.",
        )
    with keep_awake("Checking the engine"):
        return run_checks(engine)
