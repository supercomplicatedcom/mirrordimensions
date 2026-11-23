# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""Build the parts of a result that describe where and with what it ran."""

from __future__ import annotations

from mirrordimensions import plugins
from mirrordimensions.config.result import Platform, Result, WorldRef
from mirrordimensions.hostos.info import host_info


def current_platform() -> Platform:
    """The host part of the `platform` block. Engine fields are filled from M0.5."""
    host = host_info()
    return Platform(host_os=host.os, host_os_version=host.os_version, host_arch=host.arch)


def new_result(
    run_id: str, world: WorldRef, org: str | None = None, user: str | None = None
) -> Result:
    """A result envelope recording the platform and every plug-in loaded for the run."""
    return Result(
        run_id=run_id,
        status="errored",
        isolation="failed",
        world=world,
        platform=current_platform(),
        plugins=plugins.discover(),
        org=org,
        user=user,
    )
