# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""Engine service functions (host-level, not per project)."""

from __future__ import annotations

from collections.abc import Callable

from mirrordimensions.engine.base import EngineStatus, Resources, UpdateOutcome
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
    microvm: bool = False,
) -> EngineStatus:
    engine = get_engine(driver)
    with keep_awake("Setting up the engine"):
        if isinstance(engine, WslEngine):
            status = engine.setup(
                resources or default_resources(), on_step, experimental=experimental
            )
        elif isinstance(engine, LimaEngine):
            status = engine.setup(resources or default_resources(), on_step, microvm=microvm)
        else:
            if microvm:
                raise MirrorError(
                    "The host driver does not set up microVMs.",
                    "On a Linux host, install Kata Containers yourself, or use the lima driver.",
                    "Run: mirror engine setup --driver lima --microvm",
                )
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


def _quiet(_text: str) -> None:
    return None


def update_engine(*, restart: bool = False, on_step: StepFn = None) -> UpdateOutcome:
    """Install the engine's pending package updates (decision 0019).

    Only while nothing runs in it: an update can restart Docker, which would stop a run or
    a world. With `restart`, an engine that needs a restart for the update (a new kernel)
    is stopped and started again."""
    from mirrordimensions.engine.docker_api import Docker

    engine = get_engine()
    status = engine.status()
    if status.state != "running":
        raise MirrorError(
            "The engine is not running.",
            f"Its state is {status.state}; updates are installed in a running engine.",
            "Run: mirror engine start",
        )
    running = int(Docker(engine.docker_endpoint()).info().get("ContainersRunning", 0))
    if running:
        raise MirrorError(
            f"{running} container(s) are running in the engine.",
            "An update can restart Docker, which would stop a run or a world part-way.",
            "Wait for any run to end, then run: mirror down",
        )
    say = on_step or _quiet
    say("Installing the engine's updates (this can take a few minutes)")
    with keep_awake("Updating the engine"):
        outcome = engine.update()
        if outcome.reboot_required and restart:
            say("Restarting the engine to finish the update")
            engine.stop()
            started = engine.start(on_step)
            outcome.kernel = started.versions.get("kernel", outcome.kernel)
            outcome.reboot_required = started.versions.get("reboot") == "yes"
    return outcome
