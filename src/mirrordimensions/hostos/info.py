# SPDX-License-Identifier: Apache-2.0
"""Facts about the host, for status output and the `platform` block of results."""

from __future__ import annotations

import platform
import sys
from typing import Literal

from pydantic import BaseModel

HostOS = Literal["macos", "windows", "linux", "other"]
Arch = Literal["arm64", "x64", "other"]


class HostInfo(BaseModel):
    os: HostOS
    os_version: str
    arch: Arch
    python: str


def is_windows() -> bool:
    return sys.platform == "win32"


def host_os() -> HostOS:
    if sys.platform == "darwin":
        return "macos"
    if sys.platform == "win32":
        return "windows"
    if sys.platform.startswith("linux"):
        return "linux"
    return "other"


def host_arch() -> Arch:
    machine = platform.machine().lower()
    if machine in {"arm64", "aarch64"}:
        return "arm64"
    if machine in {"x86_64", "amd64"}:
        return "x64"
    return "other"


def host_info() -> HostInfo:
    system = host_os()
    if system == "macos":
        version = platform.mac_ver()[0]
    elif system == "windows":
        version = platform.version()
    else:
        version = platform.release()
    return HostInfo(
        os=system,
        os_version=version,
        arch=host_arch(),
        python=platform.python_version(),
    )
