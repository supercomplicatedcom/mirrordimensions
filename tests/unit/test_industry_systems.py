# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""An industry proposes the systems such a company runs; `world add` adds more later
(decision 0028, points 3 and 4)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from mirrordimensions.catalog.index import match_systems
from mirrordimensions.config.loader import load_model
from mirrordimensions.config.manifest import Manifest
from mirrordimensions.errors import MirrorError
from mirrordimensions.project import Project
from mirrordimensions.service import validate, worlddef
from mirrordimensions.world import profile as profiles


def mirror(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "mirrordimensions", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
        encoding="utf-8",
        stdin=subprocess.DEVNULL,
    )


def _products(root: Path) -> set[str]:
    manifest, problems = load_model(root / "mirror.yaml", Manifest)
    assert manifest is not None, problems
    return {a.product or "" for a in manifest.apps}


@pytest.mark.parametrize("slug", profiles.available())
def test_every_profiles_systems_are_in_the_catalog(slug: str) -> None:
    p = profiles.load(slug)
    for match in match_systems(p.systems.typical + p.systems.common):
        assert match.entry is not None, (slug, match.query)


def test_an_industry_proposes_its_systems_and_says_what_runs() -> None:
    proposal = worlddef.propose("Software")
    assert proposal is not None
    assert "github" in proposal.systems and "slack" in proposal.systems
    assert "GitHub: Gitea runs in its place" in proposal.lines
    assert any(line.endswith("no twin yet, recorded and left out") for line in proposal.lines)
    assert worlddef.propose("lunar shipbuilding") is None
    assert worlddef.propose(None) is None


def test_yes_uses_the_proposal(tmp_path: Path) -> None:
    done = mirror(
        "world",
        "new",
        "a",
        "--industry",
        "software",
        "--company",
        "Wexford Software",
        "--yes",
        cwd=tmp_path,
    )
    assert done.returncode == 0, done.stderr
    assert "usually runs" in done.stdout
    assert {"gitea", "mattermost", "jira", "okta"} <= _products(tmp_path / "a")
    assert validate(Project(root=tmp_path / "a")) == []


def test_without_yes_and_no_terminal_the_template_stays(tmp_path: Path) -> None:
    done = mirror("world", "new", "b", "--industry", "software", cwd=tmp_path)
    assert done.returncode == 0, done.stderr
    assert "Add --yes to use these" in done.stdout
    assert _products(tmp_path / "b") == {"gitea", "mattermost"}


def test_add_systems_adds_to_the_template(tmp_path: Path) -> None:
    done = mirror("world", "new", "c", "--add-systems", "jira", cwd=tmp_path)
    assert done.returncode == 0, done.stderr
    assert _products(tmp_path / "c") == {"gitea", "mattermost", "jira"}


def test_world_add_keeps_the_rest_of_the_file(tmp_path: Path) -> None:
    root = worlddef.new_world(tmp_path / "d", template="software-team", seed=7)
    path = root / "mirror.yaml"
    hand = path.read_text(encoding="utf-8").replace("apps:\n", "# our own note, kept\napps:\n", 1)
    path.write_text(hand, encoding="utf-8")
    added = worlddef.add_systems(Project(root=root), ["confluence", "google workspace"])
    assert added == ["collaboration", "wiki"]
    text = path.read_text(encoding="utf-8")
    assert "# our own note, kept" in text
    assert "workspace." in text and "wiki." in text
    assert validate(Project(root=root)) == []
    with pytest.raises(MirrorError, match="already has"):
        worlddef.add_systems(Project(root=root), ["confluence"])


def test_world_add_puts_a_stand_in_only_where_none_runs(tmp_path: Path) -> None:
    root = worlddef.new_world(tmp_path / "e", systems=["jira", "gitea"], seed=7)
    worlddef.add_systems(Project(root=root), ["slack", "github"])
    manifest, _ = load_model(root / "mirror.yaml", Manifest)
    assert manifest is not None
    by_kind = {a.kind: a for a in manifest.apps}
    assert by_kind["team-chat"].product == "mattermost"  # in place of Slack
    # Gitea already runs, so GitHub is recorded but not stood in for twice.
    github = next(a for a in manifest.apps if a.product == "github")
    assert github.build == "unavailable"
