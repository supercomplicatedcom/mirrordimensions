# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""MirrorDimensions: a sealed test range for AI agents."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("mirrordimensions")
except PackageNotFoundError:  # running from a source tree without installation
    __version__ = "0.0.0"

__all__ = ["__version__"]
