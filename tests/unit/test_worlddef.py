# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""Defining a world: templates, named systems, cloning, state, and what a change re-runs."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from mirrordimensions.config.loader import load_model
from mirrordimensions.config.manifest import Manifest
from mirrordimensions.errors import MirrorError
from mirrordimensions.network.sandbox import plan_from
from mirrordimensions.project import Project
from mirrordimensions.service import validate
from mirrordimensions.service.world import diff_dumps, run_stages
from mirrordimensions.service.worlddef import (
    STAGES,
    clone_world,
    definition_hash,
    first_stage_affected,
    new_world,
    resume_stage,
    system_notes,
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


HASHES = {"company": "a", "systems": "b", "data": "c", "rules": "d"}


class _Recorder:
    def __init__(self) -> None:
        self.ran: list[int] = []
        self.record: dict[str, Any] = {}

    def stages(self, failing: int | None) -> list[Callable[[], None]]:
        return [self._stage(n, n == failing) for n in range(1, len(STAGES) + 1)]

    def _stage(self, n: int, fail: bool) -> Callable[[], None]:
        def stage() -> None:
            self.ran.append(n)
            if fail:
                raise MirrorError(f"stage {n} broke", "", "")

        return stage

    def save(self, stage: int, failed: str | None) -> None:
        self.record.update(last_stage=stage, failed=failed, hashes=HASHES)


@pytest.mark.parametrize("failing", range(1, len(STAGES) + 1))
def test_a_failure_at_any_stage_resumes_there(failing: int) -> None:
    r = _Recorder()
    with pytest.raises(MirrorError):
        run_stages(r.stages(failing), 1, r.save)
    assert r.record["last_stage"] == failing - 1
    assert f"stage {failing}" in str(r.record["failed"])
    # --resume starts at the stage that failed and runs only it and what follows.
    start = resume_stage(r.record, HASHES, resume=True, from_stage=None)
    assert start == failing
    r.ran.clear()
    assert run_stages(r.stages(None), start, r.save) == len(STAGES)
    assert r.ran == list(range(failing, len(STAGES) + 1))
    assert r.record["failed"] is None


def test_resume_after_a_change_reruns_only_what_it_affects() -> None:
    from mirrordimensions.service.worlddef import resume_stage

    done = {
        "last_stage": 8,
        "failed": None,
        "hashes": {"company": "a", "systems": "b", "data": "c", "rules": "d"},
    }
    same = dict(done["hashes"])  # type: ignore[arg-type]
    assert resume_stage(done, same, resume=True, from_stage=None) == 9  # nothing to do
    assert resume_stage(done, {**same, "rules": "x"}, resume=True, from_stage=None) == 9
    assert resume_stage(done, {**same, "data": "x"}, resume=True, from_stage=None) == 4
    assert resume_stage(done, {**same, "company": "x"}, resume=False, from_stage=None) == 1
    assert resume_stage(done, same, resume=False, from_stage=6) == 6


def test_an_interrupted_draft_resumes_at_its_next_question(tmp_path: Path) -> None:
    from mirrordimensions.service.worlddef import (
        finish_draft,
        load_draft,
        next_question,
        save_draft,
    )
    from mirrordimensions.world.names import suggest_company

    root = tmp_path / "drafted"
    draft = load_draft(root)
    assert next_question(draft) == "company"
    draft.company = suggest_company(draft.seed, attempt=1)
    draft.template = "software-team"
    save_draft(root, draft)  # the session stops here
    again = load_draft(root)
    assert again.company == draft.company
    assert next_question(again) == "people"
    again.people, again.history = 40, 365
    made = finish_draft(root, again)
    manifest, _ = load_model(made / "mirror.yaml", Manifest)
    assert manifest is not None
    assert (manifest.company.name, manifest.company.size, manifest.company.history_days) == (
        draft.company.name,
        40,
        365,
    )
    assert not (made / ".mirror" / "draft.json").exists()


def test_a_product_without_a_twin_gets_the_twin_of_its_kind(tmp_path: Path) -> None:
    root = new_world(tmp_path / "w", systems=["Slack", "GitHub", "Jira"], seed=7)
    manifest, _ = load_model(root / "mirror.yaml", Manifest)
    assert manifest is not None
    apps = {a.id: a for a in manifest.apps}
    # The template's ids, which agent files grant by, whichever way the world was defined.
    assert (apps["chat"].product, apps["chat"].in_place_of) == ("mattermost", "slack")
    assert (apps["code"].product, apps["code"].in_place_of) == ("gitea", "github")
    assert apps["ticketing"].build == "unavailable"
    assert sorted(a.product or "" for a in plan_from(manifest).apps) == ["gitea", "mattermost"]
    notes = system_notes(manifest)
    assert any("Mattermost runs in its place" in n for n in notes)
    assert any(n.startswith("Jira has no twin yet") for n in notes)


def test_substitution_can_be_turned_off_and_is_never_doubled(tmp_path: Path) -> None:
    off = new_world(tmp_path / "a", systems=["Gitea", "Slack"], seed=7, substitute=False)
    manifest, _ = load_model(off / "mirror.yaml", Manifest)
    assert manifest is not None
    assert {a.product: a.build for a in manifest.apps} == {"gitea": None, "slack": "unavailable"}
    both = new_world(tmp_path / "b", systems=["Gitea", "GitHub"], seed=7)
    manifest, _ = load_model(both / "mirror.yaml", Manifest)
    assert manifest is not None
    assert [(a.id, a.product, a.build) for a in manifest.apps] == [
        ("code", "gitea", None),
        ("code-2", "github", "unavailable"),
    ]
    assert len({a.hostname for a in manifest.apps}) == 2


def test_a_world_that_could_build_nothing_is_refused(tmp_path: Path) -> None:
    with pytest.raises(MirrorError, match="None of these systems can be built yet"):
        new_world(tmp_path / "w", systems=["Jira", "ServiceNow"], seed=7)
    assert not (tmp_path / "w" / "mirror.yaml").exists()
