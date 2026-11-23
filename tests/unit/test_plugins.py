# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""A plug-in from another package registers, shows in status, and is recorded in results."""

from __future__ import annotations

from pathlib import Path

from mirrordimensions import plugins
from mirrordimensions.config.result import WorldRef
from mirrordimensions.service import status
from mirrordimensions.service.results import new_result


def test_test_plugin_is_discovered() -> None:
    names = {(p.group, p.name, p.distribution) for p in plugins.discover()}
    assert ("run_store", "memory", "md-testplugin") in names
    assert ("sink", "collect", "md-testplugin") in names


def test_plugin_loads() -> None:
    store_class = plugins.load("run_store", "memory")
    assert store_class().name == "memory"


def test_plugin_appears_in_status(project_dir: Path) -> None:
    assert any(p.name == "memory" for p in status(project_dir).plugins)


def test_plugin_is_recorded_in_a_result() -> None:
    result = new_result(
        "r_abcd1234", WorldRef(name="northfield-ops", seed=48213, definition_hash="0" * 64)
    )
    assert any(p.group == "run_store" and p.name == "memory" for p in result.plugins)
    assert result.org is None
    assert result.user is None
    assert result.platform.host_os in {"macos", "windows", "linux"}


def test_every_group_is_named() -> None:
    assert set(plugins.GROUPS) == {
        "engine",
        "run_store",
        "authenticator",
        "twin",
        "importer",
        "check",
        "sink",
    }
