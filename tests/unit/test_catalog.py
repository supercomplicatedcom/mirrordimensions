# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""The catalog loads 500 entries plus the two buildable twins and resolves names safely."""

from __future__ import annotations

from mirrordimensions.catalog import index


def test_loads_500_plus_the_buildable_twins_and_the_industry_systems() -> None:
    stats = index.stats()
    # 500 from apps.csv, the two twins, and the industry systems the profiles name.
    assert stats["entries"] == 574
    assert stats["by_status"] == {"candidate": 572, "buildable": 2}


def test_industry_systems_have_their_own_kind() -> None:
    epic = index.resolve("epic")
    assert epic is not None and epic.kind == "ehr" and epic.twin_status == "candidate"


def test_names_and_aliases_resolve_ignoring_case_and_punctuation() -> None:
    assert index.resolve("Jira Cloud") is not None
    assert index.resolve("jira-cloud") == index.resolve("JIRA cloud")
    entry = index.resolve("MS Teams")
    assert entry is not None
    assert entry.kind == "team-chat"


def test_unknown_names_are_reported_not_guessed() -> None:
    matches = index.match_systems(["Gitea", "Northwind Ledger 9000"])
    assert matches[0].buildable
    assert matches[1].entry is None
    assert not matches[1].buildable


def test_candidates_are_not_buildable() -> None:
    (jira,) = index.match_systems(["jira"])
    assert jira.entry is not None
    assert not jira.buildable


def test_no_alias_collisions_and_unique_slugs() -> None:
    assert index.collisions() == []
    slugs = [e.slug for e in index.load()]
    assert len(slugs) == len(set(slugs))
