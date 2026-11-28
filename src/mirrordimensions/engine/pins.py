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

# The same release as a WSL root file system, for the wsl driver (x64 only), with the
# digest from releases.ubuntu.com/26.04/SHA256SUMS (recorded 2026-11-26).
WSL_ROOTFS = (
    "https://releases.ubuntu.com/26.04/ubuntu-26.04.1-wsl-amd64.wsl",
    "48d56724b5c8e60f24893e83e73bbb58c60b3ca22fba3da977075420acd54104",
)

# Kata Containers static releases (no published checksums; pinned on first download,
# 2026-11-23). Used only by the optional microVM runtime (decision 0012).
KATA_VERSION = "4.4.0"
KATA_SHA256 = {
    "arm64": "9dd4407d4b756858fe9ce33322a605f5a932743839a8ec47108e8513dcc3aaa3",
    "amd64": "ccbc0cbc591089d0c57012b78da64b23ef43e0bac0f869dc7bfebe8588c33986",
}
# Firecracker v1.17.0, the version Kata 4.4 is tested with; Firecracker publishes these.
FIRECRACKER_VERSION = "v1.17.0"
FIRECRACKER_SHA256 = {
    "aarch64": "e351ebe4f7a16b5873bbd51005d2e6767103cff4d5ebc829df2d3f95a93e2256",
    "x86_64": "06094a1108ae9e82aa4c23a775aa92758f53f1175d422270d9d6162cb9ade558",
}
