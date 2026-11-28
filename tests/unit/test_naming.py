# SPDX-License-Identifier: Apache-2.0
"""Each world names its core repositories and channels its own way (decision 0029)."""

from __future__ import annotations

import sys
from pathlib import Path

from ruamel.yaml import YAML

from mirrordimensions.config.manifest import Manifest
from mirrordimensions.runner import scenario
from mirrordimensions.service.project import render_manifest
from mirrordimensions.world import naming
from mirrordimensions.world.generate import generate
from mirrordimensions.world.model import World
from mirrordimensions.world.names import suggest_company

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import portal_fixture  # tests/portal_fixture.py


def _world(seed: int) -> World:
    text = render_manifest("northfield-ops", suggest_company(seed), seed)
    return generate(Manifest.model_validate(YAML(typ="safe").load(text)))  # pyright: ignore[reportUnknownMemberType]


def test_names_differ_between_worlds_and_are_recorded() -> None:
    worlds = [_world(s) for s in (48213, 7, 1234, 90210)]
    billing = {naming.repos(w)["billing-service"] for w in worlds}
    assert len(billing) > 1
    for w in worlds:
        assert {r.name for r in w.repositories} == set(naming.repos(w).values())
        assert {c.name for c in w.channels} == set(naming.channels(w).values())
        # Mattermost's own channels keep their names in every world.
        assert {"town-square", "off-topic"} <= {c.name for c in w.channels}


def test_nothing_in_a_world_names_a_moved_repository_or_channel() -> None:
    w = _world(7)
    text = w.model_dump_json()
    for usual, actual in naming.repos(w).items():
        if usual != actual:
            assert f'"{usual}' not in text and f"{usual}#" not in text
    for usual, actual in naming.channels(w).items():
        if usual != actual:
            assert f"#{usual} " not in text


def test_every_builtin_scenario_translates_to_the_worlds_names() -> None:
    w = _world(7)
    names = naming.Translator(w)
    moved = {k for k, v in naming.repos(w).items() if k != v}
    assert moved
    for item in scenario.builtin().values():
        translated = type(item).model_validate(names.value(item.model_dump(by_alias=True)))
        dumped = translated.model_dump_json(by_alias=True)
        for usual in moved:
            assert usual not in dumped, (item.id, usual)


def test_people_roles_are_not_mistaken_for_channels() -> None:
    w = _world(7)
    names = naming.Translator(w)
    data = {"cast": {"asker": {"role": "support"}}, "check": {"channel": "support"}}
    out = names.value(data)
    assert out["cast"]["asker"]["role"] == "support"
    assert out["check"]["channel"] == naming.channels(w)["support"]


def test_grants_and_template_values_use_the_worlds_names() -> None:
    w = _world(7)
    names = naming.Translator(w)
    grants = names.grants({"repos": {"billing-service": "write"}, "channels": ["incidents"]})
    assert grants == {
        "repos": {naming.repos(w)["billing-service"]: "write"},
        "channels": [naming.channels(w)["incidents"]],
    }
    values = naming.template_values(w)
    assert values["repo.billing"] == naming.repos(w)["billing-service"]
    assert values["channel.incidents"] == naming.channels(w)["incidents"]


def test_text_mentions_follow_the_names() -> None:
    w = _world(7)
    names = naming.Translator(w)
    said = names.text("see billing-service#12 and ask in #incidents about incidents")
    assert naming.repos(w)["billing-service"] + "#12" in said
    assert "#" + naming.channels(w)["incidents"] in said
    assert said.endswith("about incidents")  # an ordinary word stays as it is


def test_the_grants_editor_shows_and_edits_grants_written_with_the_usual_names(
    tmp_path: Path,
) -> None:
    from mirrordimensions.service import environment
    from mirrordimensions.service.project import load_project

    root = portal_fixture.make_project(tmp_path)
    project = load_project(root)
    world = World.model_validate_json((root / ".mirror" / "world.json").read_text("utf-8"))
    usual, actual = next((u, a) for u, a in naming.repos(world).items() if u != a)
    # The agent file grants it by its usual name, as the example agents do.
    environment.set_grant(project, "scripted-good", f"code/{usual}", "write")
    code = next(s for s in environment.grant_options(project, "scripted-good") if s.key == "repos")
    # The editor shows that grant on the world's own name.
    assert next(i for i in code.items if i.name == actual).grant == "write"
    environment.set_grant(project, "scripted-good", f"code/{actual}", "read")
    text = (root / "agents" / "scripted-good.yaml").read_text("utf-8")
    assert f"{usual}: read" in text and f"{actual}:" not in text  # one entry, edited
