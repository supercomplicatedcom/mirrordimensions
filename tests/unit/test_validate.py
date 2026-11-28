# SPDX-License-Identifier: Apache-2.0
"""`mirror validate` reports every problem with its file and line."""

from __future__ import annotations

from pathlib import Path

from mirrordimensions.hostos.files import write_text
from mirrordimensions.project import Project
from mirrordimensions.service import validate


def test_reports_file_and_line(project_dir: Path) -> None:
    manifest = project_dir / "mirror.yaml"
    text = manifest.read_text(encoding="utf-8").replace(
        "visibility: granted", "visibility: hidden", 1
    )
    write_text(manifest, text)
    problems = validate(Project(root=project_dir))
    assert len(problems) == 1
    expected_line = text.splitlines().index("    visibility: hidden") + 1
    assert problems[0].file == "mirror.yaml"
    assert problems[0].line == expected_line
    assert "apps.0.visibility" in problems[0].message


def test_reports_yaml_syntax_errors(project_dir: Path) -> None:
    write_text(project_dir / "mirror.yaml", "version: 1\nname: [unclosed\n")
    problems = validate(Project(root=project_dir))
    assert problems[0].message.startswith("not valid YAML")


def test_agent_grant_for_unknown_app(project_dir: Path) -> None:
    write_text(
        project_dir / "agents" / "ops.yaml",
        "name: ops-assistant\nmode: hosted\nacts_as: {role: engineer}\n"
        "image: registry.northfield.internal/ops:1.4\nwake: {type: poll}\n"
        "grants:\n  code: {}\n  wiki: {}\n",
    )
    problems = validate(Project(root=project_dir))
    assert [(p.file, p.line) for p in problems] == [("agents/ops.yaml", 8)]
    assert "'wiki' is not an app" in problems[0].message


def test_names_that_collide_ignoring_case(project_dir: Path) -> None:
    agent = (
        "name: {name}\nmode: hosted\nacts_as: {{role: engineer}}\n"
        "image: registry.northfield.internal/ops:1.4\nwake: {{type: poll}}\n"
    )
    write_text(project_dir / "agents" / "first.yaml", agent.format(name="ops"))
    write_text(project_dir / "agents" / "second.yaml", agent.format(name="ops"))
    problems = validate(Project(root=project_dir))
    assert any("agent name 'ops' is also used in agents/first.yaml" in p.message for p in problems)


def test_scenarios_folder_is_checked(project_dir: Path) -> None:
    write_text(project_dir / "scenarios" / "broken.yaml", "id: Not-An-Id\n")
    problems = validate(Project(root=project_dir))
    assert problems
    assert all(p.file == "scenarios/broken.yaml" for p in problems)
