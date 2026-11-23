# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""Pinned versions and checksums for everything the engine downloads.

Every download is checked against the SHA-256 recorded here, not against a checksum
file fetched alongside it. Update these together, in one pull request, and record the
change in docs/platforms.md.
"""

from __future__ import annotations

from typing import Literal

LIMA_VERSION = "2.3.0"
LIMA_ARCHIVES: dict[tuple[str, str], tuple[str, str]] = {
    # (host os, host arch): (file name, sha256)
    ("macos", "arm64"): (
        "lima-2.3.0-Darwin-arm64.tar.gz",
        "b7af444bd8f91d3c307477e562f2cf3bd7595d62b9429185e4fa841563578cfc",
    ),
    ("linux", "x64"): (
        "lima-2.3.0-Linux-x86_64.tar.gz",
        "cc8ba97f1c801b899f7c9eda9919dfc4ce4fa2c140c53e5add15aa2d0a1936f9",
    ),
}


def lima_url(file_name: str) -> str:
    return f"https://github.com/lima-vm/lima/releases/download/v{LIMA_VERSION}/{file_name}"


GuestArch = Literal["aarch64", "x86_64"]

# Ubuntu 26.04 LTS cloud images, digests as published in Lima's own templates.
GUEST_IMAGES: dict[GuestArch, tuple[str, str]] = {
    "aarch64": (
        "https://cloud-images.ubuntu.com/releases/resolute/release-20261016/"
        "ubuntu-26.04-server-cloudimg-arm64.img",
        "sha256:8eb876c2ccc4b6ff89e4a65d511815923b285e04503ba465809bf587f763da24",
    ),
    "x86_64": (
        "https://cloud-images.ubuntu.com/releases/resolute/release-20261016/"
        "ubuntu-26.04-server-cloudimg-amd64.img",
        "sha256:5645d0318ad21f643ebb1ac4567514620e9893380b07b0201fda163baa5b7eb5",
    ),
}
GUEST_OS = "Ubuntu 26.04 LTS"
