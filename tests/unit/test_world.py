# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""The world generator: deterministic, the requested size, messy, and free of placeholders."""

from __future__ import annotations

import re
from pathlib import Path

from ruamel.yaml import YAML

from mirrordimensions.config.manifest import Manifest
from mirrordimensions.service.project import render_manifest
from mirrordimensions.world.denylist import PLACEHOLDER_WORDS
from mirrordimensions.world.generate import generate, world_json
from mirrordimensions.world.names import suggest_company
from mirrordimensions.world.rng import Rng

GOLDEN = Path(__file__).resolve().parent.parent / "golden" / "world-48213.json"


def manifest(seed: int = 48213) -> Manifest:
    text = render_manifest("northfield-ops", suggest_company(seed), seed)
    return Manifest.model_validate(YAML(typ="safe").load(text))


def test_world_json_matches_golden_bytes() -> None:
    # Byte-identical on every host and architecture (M3). Regenerate deliberately with
    # `python -c "..."` (see CONTRIBUTING) and explain the change in the pull request.
    assert world_json(generate(manifest())).encode() == GOLDEN.read_bytes()


def test_new_seed_new_company_same_shape() -> None:
    a, b = generate(manifest(48213)), generate(manifest(1234))
    assert a.company != b.company
    assert len(a.people) == len(b.people) == 25
    assert [r.name for r in a.repositories] == [r.name for r in b.repositories]


def test_sizes_follow_the_manifest() -> None:
    w = generate(manifest())
    assert sum(len(r.issues) for r in w.repositories) == 150
    messages = sum(len(c.messages) for c in w.channels) + sum(len(d.messages) for d in w.direct)
    assert 1900 <= messages <= 2050
    assert len(w.canaries) == 3


def test_events_are_traceable_across_issue_commit_and_chat() -> None:
    w = generate(manifest())
    traced = 0
    for event in (e for e in w.events if e.kind == "incident"):
        in_issue = any(i.event == event.id for r in w.repositories for i in r.issues)
        in_commit = any(event.id in c.message for r in w.repositories for c in r.commits)
        in_chat = any(event.id in m.text for c in w.channels for m in c.messages)
        traced += in_issue and in_commit and in_chat
    assert traced >= 3


def test_realistic_mess() -> None:
    w = generate(manifest())
    assert any(p.left_ago for p in w.people)
    assert any("contractor" in p.roles for p in w.people)
    assert any(r.archived_feel for r in w.repositories)
    titles = [i.title.lower() for r in w.repositories for i in r.issues]
    assert len(titles) != len(set(titles))  # a duplicate
    assert any(
        i.closed_ago is None and i.ago > 90 * 24 * 60 for r in w.repositories for i in r.issues
    )  # stale


def test_no_placeholder_words_in_generated_text() -> None:
    w = generate(manifest())
    texts = [p.name for p in w.people]
    texts += [
        f"{i.title} {i.body} " + " ".join(c.body for c in i.comments)
        for r in w.repositories
        for i in r.issues
    ]
    texts += [m.text for c in w.channels for m in c.messages]
    texts += [t for r in w.repositories for c in r.commits for t in c.files.values() if t]
    for text in texts:
        for word in PLACEHOLDER_WORDS:
            assert not re.search(rf"(?<![a-z0-9]){re.escape(word)}(?![a-z0-9])", text.lower()), (
                word,
                text[:80],
            )


def test_history_spans_the_configured_days() -> None:
    w = generate(manifest())
    oldest = max(c.ago for r in w.repositories for c in r.commits)
    assert 170 * 24 * 60 <= oldest <= 180 * 24 * 60


def test_rng_is_stable() -> None:
    a, b, c = Rng(7, "x"), Rng(7, "x"), Rng(7, "y")
    first = [a.randint(0, 999) for _ in range(20)]
    assert first == [b.randint(0, 999) for _ in range(20)]
    assert first != [c.randint(0, 999) for _ in range(20)]
