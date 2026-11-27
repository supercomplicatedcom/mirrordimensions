# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""Industry profiles (decision 0028) hold templates, never fixed sentences (decision 0029)."""

from __future__ import annotations

import re
from collections.abc import Iterator

import pytest
from ruamel.yaml import YAML

from mirrordimensions.config.manifest import Manifest
from mirrordimensions.service.project import render_manifest
from mirrordimensions.world import profile as profiles
from mirrordimensions.world import publictext
from mirrordimensions.world.compose import MAX_LITERAL, Composer, longest_literal
from mirrordimensions.world.denylist import PLACEHOLDER_WORDS, TELL_WORDS
from mirrordimensions.world.generate import generate
from mirrordimensions.world.names import suggest_company
from mirrordimensions.world.rng import Rng

FORBIDDEN = {w for w in PLACEHOLDER_WORDS | TELL_WORDS if " " not in w} - {"test", "tests"}


def _templates(p: profiles.Profile) -> Iterator[tuple[str, str]]:
    for name, entries in p.symbols.items():
        for entry in entries:
            yield f"symbols.{name}", entry
    for role, themes in p.issues.items():
        for i, theme in enumerate(themes):
            parts = [*theme.title, *(a for s in theme.body for a in s), *theme.comments]
            parts += [a for alts in theme.let.values() for a in alts]
            for part in parts:
                yield f"issues.{role}[{i}]", part
    for comment in p.comments:
        yield "comments", comment
    for kind, threads in p.chat.items():
        for i, thread in enumerate(threads):
            parts = [*thread.root, *(a for r in thread.replies for a in r)]
            parts += [a for alts in thread.let.values() for a in alts]
            for part in parts:
                yield f"chat.{kind}[{i}]", part
    for i, incident in enumerate(p.incidents):
        for part in [*incident.title, *incident.alert, *incident.fix_message]:
            yield f"incidents[{i}]", part
    for name, alts in p.lines.items():
        for part in alts:
            yield f"lines.{name}", part


@pytest.fixture(params=profiles.available())
def profile(request: pytest.FixtureRequest) -> profiles.Profile:
    return profiles.load(str(request.param))


def test_every_profile_loads_complete(profile: profiles.Profile) -> None:
    assert profile.slug in profiles.available()
    assert set(profiles.CORE_ROLES.values()) <= set(profile.issues)


def test_no_literal_run_is_longer_than_the_limit(profile: profiles.Profile) -> None:
    long = [(where, t) for where, t in _templates(profile) if longest_literal(t) > MAX_LITERAL]
    assert not long, long[:5]


def test_every_symbol_offers_alternatives(profile: profiles.Profile) -> None:
    # One-entry symbols would let fixed sentences through in pieces.
    single = [name for name, entries in profile.symbols.items() if len(entries) < 2]
    assert not single, single[:10]


def test_no_placeholder_or_test_words(profile: profiles.Profile) -> None:
    found = [
        (where, t)
        for where, t in _templates(profile)
        if set(re.findall(r"[a-z]+", t.lower())) & FORBIDDEN
    ]
    assert not found, found[:5]


def test_every_template_renders(profile: profiles.Profile) -> None:
    facts = {
        "company": "Halden Freight",
        "domain": "halden-freight.com",
        "org": "halden",
        "item_a": "Pallet storage",
        "item_b": "Handling fee",
        "repo": "billing-service",
        "service": "customer-portal",
        "person": "Ines",
        "day": "Thursday",
        "time": "2:30",
        "issue": "billing-service#41",
        "issue_title": "Credit note totals ignore the tax rounding",
        "version": "v1.6.0",
        "incident": "Invoice emails delayed",
        "fix": "send invoice emails through the queue",
        "title": "invoice totals off by a cent",
        "first_sentence": "Totals are off by a cent on discounted lines",
        "name": "Ines Okafor",
        "record": "acct 9F21C0AB, card ending 4417",
        "password": "Mapleq7!a3c1",
    }
    composer = Composer(Rng(3, "render"), profile.symbols, facts.get)
    for themes in profile.issues.values():
        for theme in themes:
            bound = composer.bind(theme.let)
            assert composer.render(theme.title, bound)
            for sentence in theme.body:
                composer.render(sentence, bound)
            for comment in theme.comments:
                composer.render([comment], bound)
    for threads in profile.chat.values():
        for thread in threads:
            bound = composer.bind(thread.let)
            assert composer.render(thread.root, bound)
    for name, alts in profile.lines.items():
        for alt in alts:
            assert composer.render([alt]) or name in ("release_empty",)


def test_an_unknown_industry_gets_the_general_profile() -> None:
    assert profiles.for_industry("lunar shipbuilding").slug == profiles.GENERAL


@pytest.mark.parametrize("seed", [48213, 7, 90210])
def test_a_general_world_is_not_public_text(seed: int) -> None:
    text = render_manifest("northfield-ops", suggest_company(seed), seed)
    world = generate(Manifest.model_validate(YAML(typ="safe").load(text)))  # pyright: ignore[reportUnknownMemberType]
    report = publictext.check(world)
    composed = [k for k in report.kinds if k.kind in ("issue", "comment", "chat", "direct")]
    public = sum(k.public for k in composed)
    total = sum(k.total for k in composed)
    assert total > 800
    assert public / total <= publictext.LIMIT, report.line()
