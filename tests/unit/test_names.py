# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""Generated company names are deterministic and never contain denied words."""

from __future__ import annotations

from mirrordimensions.world import denylist, seeded
from mirrordimensions.world.names import INDUSTRIES, PLACES, suggest_company


def test_every_possible_name_is_clean() -> None:
    for place in PLACES:
        for suffixes in INDUSTRIES.values():
            for suffix in suffixes:
                assert denylist.findings(f"{place} {suffix}") == [], (place, suffix)


def test_suggestion_is_stable() -> None:
    # Fixed expectations: a change here changes every world generated from this seed.
    assert suggest_company(48213).name == "Elmstead Mutual"
    assert suggest_company(48213).domain == "elmstead-mutual.com"
    assert seeded.number(1, "x") == seeded.number(1, "x")


def test_another_suggestion_for_the_same_seed() -> None:
    first = suggest_company(48213, "logistics")
    names = {suggest_company(48213, "logistics", attempt=i).name for i in range(5)}
    assert first.name in names
    assert len(names) > 1


def test_denylist_matches_whole_words_only() -> None:
    assert denylist.findings("Contest Logistics") == []
    assert denylist.findings("Test Logistics") == ["test"]
    assert denylist.findings("Mirror Health") == ["mirror"]
