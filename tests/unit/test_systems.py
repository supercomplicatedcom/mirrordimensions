# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""System commands that need no sandbox: listing, showing, rule edits, validation, dry runs."""

from __future__ import annotations

from pathlib import Path

import pytest

from mirrordimensions.errors import MirrorError
from mirrordimensions.project import Project
from mirrordimensions.service import systems, validate


def test_list_and_show(project_dir: Path) -> None:
    project = Project(root=project_dir)
    listed = {s.id: s for s in systems.list_systems(project)}
    assert listed["code"].twin and listed["code"].surfaces > 30
    detail = systems.show_system(project, "code")
    assert detail.settings["default_branch"] == "main"
    assert any(s.id == "file.write" for s in detail.surfaces)


def test_set_and_unset_rule_keep_comments(project_dir: Path) -> None:
    project = Project(root=project_dir)
    rule = {
        "name": "slow-search",
        "match": {"surface": "repo.search"},
        "output": {"delay_ms": [100, 200]},
    }
    systems.set_rule(project, "code", rule)
    text = (project_dir / "mirror.yaml").read_text(encoding="utf-8")
    assert "# Environment manifest" in text and "slow-search" in text
    assert systems.list_rules(project, "code") == [rule]
    systems.set_rule(project, "code", {**rule, "output": {"delay_ms": 5}})
    assert systems.list_rules(project, "code")[0]["output"] == {"delay_ms": 5}
    systems.remove_rule(project, "code", "slow-search")
    assert systems.list_rules(project, "code") == []
    assert "# Environment manifest" in (project_dir / "mirror.yaml").read_text(encoding="utf-8")


def test_set_rule_rejects_unknown_surfaces_and_errors(project_dir: Path) -> None:
    project = Project(root=project_dir)
    with pytest.raises(MirrorError, match="unknown surface"):
        systems.set_rule(project, "code", {"name": "x", "match": {"surface": "no.such"}})
    with pytest.raises(MirrorError, match="unknown error"):
        systems.set_rule(
            project,
            "code",
            {
                "name": "x",
                "match": {"surface": "file.write"},
                "input": {"max_body_bytes": 1, "on_reject": "teapot"},
            },
        )


def test_validate_reports_bad_rules_written_by_hand(project_dir: Path) -> None:
    path = project_dir / "mirror.yaml"
    text = path.read_text(encoding="utf-8").replace(
        "    product: gitea\n",
        "    product: gitea\n    rules:\n      - {name: x, match: {surface: no.such}}\n",
        1,
    )
    path.write_bytes(text.encode())
    problems = validate(Project(root=project_dir))
    assert any("unknown surface 'no.such'" in p.message for p in problems)


def test_try_answers_from_a_rule_without_a_sandbox(project_dir: Path) -> None:
    project = Project(root=project_dir)
    systems.set_rule(
        project,
        "code",
        {
            "name": "info",
            "match": {"method": "GET", "path": "/api/internal/build-info"},
            "output": {"respond": {"status": 200, "json": {"v": 1}}},
        },
    )
    result = systems.try_request(project, "code", "GET", "/api/internal/build-info")
    assert result.from_rule and result.status == 200 and result.body == '{"v":1}'
    with pytest.raises(MirrorError, match="sandbox is not up"):
        systems.try_request(project, "code", "GET", "/api/v1/user")
