# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""Defining a world: templates, named systems, cloning, state, and what a change re-runs."""

from __future__ import annotations

from pathlib import Path

from mirrordimensions.config.loader import load_model
from mirrordimensions.config.manifest import Manifest
from mirrordimensions.network.sandbox import plan_from
from mirrordimensions.project import Project
from mirrordimensions.service import validate
from mirrordimensions.service.world import diff_dumps
from mirrordimensions.service.worlddef import (
    clone_world,
    definition_hash,
    first_stage_affected,
    new_world,
    world_status,
)


def test_template_and_named_systems(tmp_path: Path) -> None:
    root = new_world(tmp_path / "a", template="software-team", seed=7)
    assert validate(Project(root=root)) == []
    named = new_world(
        tmp_path / "b", systems=["Gitea", "Jira Cloud", "Northwind Ledger 9000"], seed=7
    )
    manifest, _ = load_model(named / "mirror.yaml", Manifest)
    assert manifest is not None
    by_product = {a.product: a for a in manifest.apps}
    assert by_product["gitea"].build is None
    assert by_product["jira"].build == "unavailable"
    assert "Northwind Ledger 9000: not in the catalog" in (named / "mirror.yaml").read_text(
        encoding="utf-8"
    )
    # Unavailable systems are recorded but left out of creation.
    assert [a.product for a in plan_from(manifest).apps] == ["gitea"]


def test_state_and_stage_invalidation(tmp_path: Path) -> None:
    root = new_world(tmp_path / "w", seed=7)
    assert world_status(Project(root=root)).state == "defined"
    manifest, _ = load_model(root / "mirror.yaml", Manifest)
    assert manifest is not None
    base = definition_hash(manifest)
    assert first_stage_affected(base, base) == 9
    assert first_stage_affected({**base, "rules": "x"}, base) == 9  # a rule change re-runs nothing
    assert first_stage_affected({**base, "data": "x"}, base) == 4
    assert first_stage_affected({**base, "systems": "x"}, base) == 2
    assert first_stage_affected({**base, "company": "x"}, base) == 1


def test_clone_with_a_new_seed_keeps_the_shape(tmp_path: Path) -> None:
    src = new_world(tmp_path / "src", seed=7)
    same = clone_world(src, tmp_path / "same")
    other = clone_world(src, tmp_path / "other", new_seed=True)
    a, _ = load_model(src / "mirror.yaml", Manifest)
    b, _ = load_model(same / "mirror.yaml", Manifest)
    c, _ = load_model(other / "mirror.yaml", Manifest)
    assert a is not None and b is not None and c is not None
    assert a.company == b.company
    assert c.company.seed != a.company.seed
    assert [x.kind for x in c.apps] == [x.kind for x in a.apps]


def test_diff_dumps_names_each_difference() -> None:
    before = {"repos": [{"name": "a", "issues": [1, 2]}], "users": ["x"]}
    after = {"repos": [{"name": "a", "issues": [1, 3]}], "users": ["x"]}
    assert diff_dumps(before, before) == []
    assert diff_dumps(before, after) == ["/repos[0]/issues[1]"]
