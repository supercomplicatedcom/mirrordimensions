# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""Per-user folders for host-level state: engine settings, Docker client keys, Lima's home.

These never live inside a project, so a project folder stays portable between hosts.
"""

from __future__ import annotations

from pathlib import Path

from platformdirs import user_config_path, user_data_path

APP = "mirrordimensions"


def config_dir() -> Path:
    return user_config_path(APP, appauthor=False)


def data_dir() -> Path:
    return user_data_path(APP, appauthor=False)
