# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""The public-text check (decision 0029)."""

from __future__ import annotations

from pathlib import Path

from ruamel.yaml import YAML

from mirrordimensions.config.manifest import Manifest
from mirrordimensions.service.project import render_manifest
from mirrordimensions.world import publictext
from mirrordimensions.world.generate import generate
from mirrordimensions.world.model import Comment, Issue, Repository, World
from mirrordimensions.world.names import suggest_company


def _world(issues: list[Issue]) -> World:
    return World(
        seed=1,
        company="Halden Freight",
        domain="halden-freight.com",
        industry="logistics",
        org="halden",
        team="engineering",
        departments=[],
        people=[],
        projects=[],
        repositories=[
            Repository(
                name="ops",
                project="Ops",
                language="Python",
                description="",
                commits=[],
                issues=issues,
            )
        ],
        channels=[],
        direct=[],
        events=[],
        canaries=[],
    )


def test_a_run_of_eight_public_words_counts_and_seven_does_not() -> None:
    grams = publictext.gram_set(
        ["the nightly freight manifest export skipped every second depot today"]
    )
    eight = Issue(
        number=1,
        title="Export",
        body="Since Monday the nightly freight manifest export skipped every second depot.",
        author="p001",
        ago=10,
    )
    seven = Issue(
        number=2,
        title="Export",
        body="Our nightly freight manifest export skipped every other depot yesterday.",
        author="p001",
        ago=10,
        comments=[Comment(ago=5, author="p001", body="ok")],
    )
    report = publictext.check(_world([eight, seven]), grams)
    issue = next(k for k in report.kinds if k.kind == "issue")
    assert (issue.public, issue.total) == (1, 2)
    # Texts too short to hold a run are not counted either way.
    assert next(k for k in report.kinds if k.kind == "comment").total == 0
    assert not report.within_limit


def test_case_and_punctuation_do_not_hide_a_run() -> None:
    grams = publictext.gram_set(["The invoice total is off by one cent on discounts"])
    issue = Issue(
        number=1,
        title="Totals",
        body="THE invoice-total is off, by one cent, on discounts!",
        author="p001",
        ago=1,
    )
    assert publictext.check(_world([issue]), grams).public == 1


def test_the_corpus_is_the_package_and_skips_the_built_portal() -> None:
    files = publictext.corpus_files(publictext.package_root())
    names = {p.relative_to(publictext.package_root()).as_posix() for p in files}
    assert "world/generate.py" in names
    assert not any(n.startswith(("portal/static", "portal/web")) for n in names)


def test_repository_files_are_still_reported() -> None:
    # Composed text is under the limit (test_profiles.py). The code in the core repositories
    # is still fixed (content.py), and the check says so rather than hiding it.
    seed = 48213
    text = render_manifest("northfield-ops", suggest_company(seed), seed)
    world = generate(Manifest.model_validate(YAML(typ="safe").load(text)))  # pyright: ignore[reportUnknownMemberType]
    report = publictext.check(world)
    files = next(k for k in report.kinds if k.kind == "file")
    assert files.public > files.total // 2
    assert "decision 0029" in report.line()


def test_the_package_root_is_the_installed_package() -> None:
    assert (publictext.package_root() / "world" / "publictext.py").is_file()
    assert isinstance(publictext.package_root(), Path)


def test_a_yaml_comment_does_not_hide_a_run(tmp_path: Path) -> None:
    folder = tmp_path / "pkg"
    folder.mkdir()
    (folder / "p.yaml").write_text(
        "- the nightly freight manifest export\n# a comment between\n- skipped every second depot today\n",
        encoding="utf-8",
    )
    publictext.package_grams.cache_clear()
    grams = publictext.package_grams(folder)
    issue = Issue(
        number=1,
        title="Export",
        body="The nightly freight manifest export skipped every second depot today.",
        author="p001",
        ago=1,
    )
    assert publictext.check(_world([issue]), grams).public == 1
