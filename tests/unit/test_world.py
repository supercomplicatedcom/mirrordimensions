# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""The world generator: deterministic, the requested size, messy, and free of placeholders."""

from __future__ import annotations

import re
import subprocess
import sys
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
    # An incident has its ticket, a fix that references the ticket, and a thread that links
    # it, the way people link work; no generator ids in the text.
    w = generate(manifest())
    traced = 0
    for event in (e for e in w.events if e.kind == "incident"):
        repo = next(r for r in w.repositories if r.name == event.repository)
        issue = next(i for i in repo.issues if i.event == event.id)
        in_commit = any(f"(#{issue.number})" in c.message for c in repo.commits)
        ref = f"{repo.name}#{issue.number}"
        in_chat = any(ref in m.text for c in w.channels for m in c.messages)
        traced += in_commit and in_chat
    assert traced == 6
    texts = [c.message for r in w.repositories for c in r.commits]
    texts += [m.text for c in w.channels for m in c.messages]
    assert not [t for t in texts if re.search(r"\(e\d\d\)", t)]


def test_realistic_mess() -> None:
    w = generate(manifest())
    assert any(p.left_ago for p in w.people)
    assert any("contractor" in p.roles for p in w.people)
    assert any(r.archived_feel for r in w.repositories)
    titles = [i.title.lower() for r in w.repositories for i in r.issues]
    assert len(titles) == len(set(titles)) + 1  # one duplicate, nothing else recycled
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


def test_nothing_repeats_the_way_a_generator_would() -> None:
    w = generate(manifest())
    # Chat: every message is its own, apart from short acknowledgements.
    texts = [m.text for c in w.channels for m in c.messages]
    texts += [m.text for d in w.direct for m in d.messages]
    repeated = {t for t in texts if texts.count(t) > 1 and len(t) > 12}
    assert not repeated, sorted(repeated)[:5]
    # Titles carry no recycled suffixes; branches are named for their work.
    for r in w.repositories:
        for i in r.issues:
            assert not re.search(r"\((again|follow-up|part \d|staging|mobile|Q\d)\)$", i.title)
        for name in r.branches:
            assert not re.search(r"-\d+$", name), name
    # Commits make real changes: no filler comments appended to code.
    for r in w.repositories:
        for c in r.commits:
            for text in c.files.values():
                assert "# reviewed" not in (text or "") and "# tidy up" not in (text or "")


def test_names_are_distinct() -> None:
    for seed in (48213, 1234, 99):
        people = generate(manifest(seed)).people
        firsts = [p.name.split()[0] for p in people]
        lasts = [p.name.split()[-1] for p in people]
        assert len(set(firsts)) == len(firsts)
        assert len(set(lasts)) == len(lasts)


def test_issue_numbers_follow_time() -> None:
    for r in generate(manifest()).repositories:
        agos = [i.ago for i in sorted(r.issues, key=lambda i: i.number)]
        assert agos == sorted(agos, reverse=True)


def test_every_repository_s_own_tests_pass(tmp_path: Path) -> None:
    # The code an agent is asked to work on is real: its unit tests pass at the head.
    w = generate(manifest())
    for r in w.repositories:
        files: dict[str, str] = {}
        for c in sorted(r.commits, key=lambda c: -c.ago):
            for path, text in c.files.items():
                if text is None:
                    files.pop(path, None)
                else:
                    files[path] = text
        if not any(p.startswith("tests/") for p in files):
            continue
        root = tmp_path / r.name
        for path, text in files.items():
            (root / path).parent.mkdir(parents=True, exist_ok=True)
            (root / path).write_text(text, encoding="utf-8")
        done = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(root / "tests")],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        assert done.returncode == 0, (r.name, done.stdout[-800:])


def test_release_notes_list_only_shipped_changes() -> None:
    w = generate(manifest())
    releases = next(c for c in w.channels if c.name == "releases").messages
    assert releases
    for m in releases:
        for line in m.text.splitlines()[1:]:
            assert not line.rstrip().removesuffix(")").rsplit(" (#", 1)[0].endswith("?"), line


def test_chat_names_running_services_for_operations() -> None:
    w = generate(manifest())
    texts = [m.text for c in w.channels for m in c.messages]
    texts += [m.text for d in w.direct for m in d.messages]
    for text in texts:
        assert not re.search(
            r"(deploy\w*|backup|restore|rollback|scal\w+)\b[^.#]*\b(platform-docs|infra-config|ops-scripts)\b(?!#)",
            text,
            re.IGNORECASE,
        ), text


def test_a_conversation_does_not_recur_within_weeks() -> None:
    w = generate(manifest())
    for c in w.channels:
        roots = [m for m in c.messages if m.reply_to is None]
        for i, a in enumerate(roots):
            stem = " ".join(re.sub(r"\S+#\d+", "#", a.text).split()[:6])
            for b in roots[i + 1 :]:
                if abs(a.ago - b.ago) >= 21 * 24 * 60:
                    break
                other = " ".join(re.sub(r"\S+#\d+", "#", b.text).split()[:6])
                assert len(stem.split()) < 6 or stem != other, (c.name, a.text, b.text)


def test_people_started_at_their_own_time_of_day() -> None:
    people = generate(manifest()).people
    minutes = [p.started_ago % (24 * 60) for p in people]
    assert len(set(minutes)) > len(people) - 3
