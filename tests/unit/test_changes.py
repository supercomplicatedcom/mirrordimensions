# SPDX-License-Identifier: Apache-2.0
"""M7: edits and pending changes (decision 0021). Visibility, grants and rules are saved at
once and take effect at the next run; what changes the built world waits for a rebuild."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from ruamel.yaml import YAML
from typer.testing import CliRunner

from mirrordimensions.cli.app import app
from mirrordimensions.config.manifest import Manifest
from mirrordimensions.errors import MirrorError
from mirrordimensions.network import sandbox
from mirrordimensions.service import environment as env
from mirrordimensions.service import load_project
from mirrordimensions.service import systems as systems_svc
from mirrordimensions.service.agents import _manifest  # pyright: ignore[reportPrivateUsage]
from mirrordimensions.service.changes import record_applied, record_built
from mirrordimensions.service.worlddef import definition_hash, first_stage_affected

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import portal_fixture


@pytest.fixture
def root(tmp_path: Path) -> Path:
    made = portal_fixture.make_project(tmp_path)
    project = load_project(made)
    record_built(project, _manifest(project))  # as if the world had just been built
    return made


def _whats(root: Path) -> list[tuple[str, str]]:
    return [(c.applies, c.what) for c in env.pending_changes(load_project(root))]


def test_nothing_is_pending_right_after_a_build(root: Path) -> None:
    assert _whats(root) == []


def test_visibility_applies_at_the_next_run_unless_a_system_comes_or_goes(root: Path) -> None:
    project = load_project(root)
    change = env.set_visibility(project, "chat", "denied")
    assert (change.before, change.after, change.applies) == ("granted", "denied", "next run")
    text = (root / "mirror.yaml").read_text(encoding="utf-8")
    assert "visibility: denied" in text
    assert _whats(root) == [("next run", "Team chat: visibility granted to denied")]
    # Absent changes what runs and what DNS answers: the sandbox restarts. The system's data
    # is in the snapshot, so bringing it back is a restart too.
    assert env.set_visibility(project, "code", "absent").applies == "restart"
    assert ("restart", "Code hosting: visibility granted to absent") in _whats(root)
    with pytest.raises(MirrorError, match="not a visibility"):
        env.set_visibility(project, "chat", "hidden")


def test_a_run_puts_rules_and_visibility_into_effect(root: Path) -> None:
    project = load_project(root)
    env.set_visibility(project, "chat", "present")
    rule = {"name": "slow-search", "match": {"surface": "repo.search"}, "output": {"delay_ms": 800}}
    systems_svc.set_rule(project, "code", rule)
    assert [w for _, w in _whats(root)] == [
        "Team chat: visibility granted to present",
        "Code hosting: rule slow-search added",
    ]
    record_applied(project, _manifest(project))  # what a run, apply or up does
    assert _whats(root) == []
    change = systems_svc.remove_rule(project, "code", "slow-search")
    assert change.applies == "next run" and change.after is None
    assert _whats(root) == [("next run", "Code hosting: rule slow-search removed")]


def test_visibility_no_longer_rebuilds_the_world(root: Path) -> None:
    manifest = Manifest.model_validate(
        YAML(typ="safe").load((root / "mirror.yaml").read_text(encoding="utf-8"))
    )
    before = definition_hash(manifest)
    moved = manifest.model_copy(deep=True)
    moved.apps[1].visibility = "denied"
    assert first_stage_affected(before, definition_hash(moved)) == 9  # nothing to re-run
    gone = manifest.model_copy(deep=True)
    gone.apps[1].visibility = "absent"
    assert first_stage_affected(before, definition_hash(gone)) == 9  # a restart, not a rebuild
    # A system the world was built without needs building when it is wanted.
    assert first_stage_affected(definition_hash(gone), before) == 2
    # A world recorded before visibility left the "systems" hash is not taken for stale.
    legacy = {k: v for k, v in before.items() if k != "absent"} | {"systems": before["systems_v1"]}
    assert first_stage_affected(legacy, definition_hash(manifest)) == 9
    assert first_stage_affected(legacy, definition_hash(moved)) == 2


def test_grants_are_edited_in_the_agent_file_keeping_its_comments(root: Path) -> None:
    project = load_project(root)
    path = root / "agents" / "scripted-good.yaml"
    path.write_text("# kept\n" + path.read_text(encoding="utf-8"), encoding="utf-8")
    change = env.set_grant(project, "scripted-good", "code/infra-config", "read")
    assert (change.before, change.after, change.applies) == (None, "read", "next run")
    env.set_grant(project, "scripted-good", "code/billing-service", "admin")
    env.set_grant(project, "scripted-good", "code/platform-docs", "none")
    env.set_grant(project, "scripted-good", "chat/#off-topic", "member")
    env.set_grant(project, "scripted-good", "chat/incidents", "none")
    text = path.read_text(encoding="utf-8")
    assert text.startswith("# kept\n")
    grants = YAML(typ="safe").load(text)["grants"]
    assert grants["code"]["repos"] == {"billing-service": "admin", "infra-config": "read"}
    assert grants["chat"]["channels"] == ["platform-team", "engineering", "releases", "off-topic"]
    assert env.set_grant(project, "scripted-good", "chat/off-topic", "member").before == "member"
    env.set_grant(project, "scripted-good", "chat", "none")
    assert "chat" not in YAML(typ="safe").load(path.read_text(encoding="utf-8"))["grants"]


@pytest.mark.parametrize(
    ("resource", "grant", "message"),
    [
        ("code/billing-service", "owner", "not a grant for code"),
        ("code/no-such-repo", "read", "has no repo called"),
        ("chat/no-such-channel", "member", "has no channel called"),
        ("code", "write", "granted or not"),
        ("nowhere/x", "read", "no system 'nowhere'"),
    ],
)
def test_a_grant_that_names_nothing_real_is_refused(
    root: Path, resource: str, grant: str, message: str
) -> None:
    with pytest.raises(MirrorError, match=message):
        env.set_grant(load_project(root), "scripted-good", resource, grant)


def test_grants_changed_since_an_agents_last_run_are_pending(root: Path) -> None:
    project = load_project(root)
    good = YAML(typ="safe").load((root / "agents" / "scripted-good.yaml").read_text("utf-8"))
    record_applied(project, _manifest(project), "scripted-good", good["grants"])
    assert _whats(root) == []
    env.set_grant(project, "scripted-good", "code/infra-config", "read")
    assert _whats(root) == [("next run", "scripted-good: grants changed since its last run")]


def test_the_gateway_gets_new_rules_but_keeps_what_up_resolved() -> None:
    manifest = Manifest.model_validate(
        {
            "version": 1,
            "name": "w",
            "company": {"name": "Elmstead Mutual", "domain": "elmstead-mutual.com", "seed": 3},
            "apps": [
                {"id": "code", "product": "gitea", "hostname": "git.elmstead-mutual.com"},
                {"id": "chat", "product": "mattermost", "hostname": "chat.elmstead-mutual.com"},
            ],
        }
    )
    plan = sandbox.plan_from(manifest, Path("."))
    current = json.loads(sandbox.routes_json(plan, ["s3cret"]))
    current["routes"]["api.anthropic.com"] = {"upstream": "https://1.2.3.4:443", "model": {}}
    manifest.apps[0].rules = []
    manifest.apps[1].visibility = "denied"
    later = sandbox.plan_from(manifest, Path("."))
    fresh = json.loads(sandbox.refreshed_routes(json.dumps(current).encode(), later))
    assert fresh["routes"]["chat.elmstead-mutual.com"]["visibility"] == "denied"
    assert fresh["routes"]["api.anthropic.com"] == current["routes"]["api.anthropic.com"]
    assert fresh["secrets"] == current["secrets"] and fresh["seed"] == current["seed"]


def test_the_commands(root: Path) -> None:
    runner = CliRunner()

    def mirror(*args: str) -> str:
        out = runner.invoke(app, ["--project", str(root), *args])
        assert out.exit_code == 0, out.output
        return out.output

    assert "nothing pending" in mirror("changes")
    assert "takes effect at the next run" in mirror("set", "visibility", "chat", "denied")
    assert "when the sandbox restarts" in mirror("set", "visibility", "code", "absent")
    mirror("set", "grant", "scripted-good", "code/infra-config", "write")
    listed = mirror("changes")
    assert "next run  Team chat: visibility granted to denied" in listed
    assert "restart   Code hosting: visibility granted to absent" in listed
    assert "mirror apply" in listed
    as_json = json.loads(mirror("--json", "changes"))
    assert {c["applies"] for c in as_json} == {"next run", "restart"}


def test_a_run_tells_the_gateway_whose_requests_are_whose() -> None:
    manifest = Manifest.model_validate(
        {
            "version": 1,
            "name": "w",
            "company": {"name": "Elmstead Mutual", "domain": "elmstead-mutual.com", "seed": 3},
            "apps": [{"id": "code", "product": "gitea", "hostname": "git.elmstead-mutual.com"}],
        }
    )
    plan = sandbox.plan_from(manifest, Path("."))
    current = sandbox.routes_json(plan, [])
    fresh = json.loads(sandbox.refreshed_routes(current, plan, {"10.40.0.5": "ops"}))
    assert fresh["identities"] == {"10.40.0.5": "ops"}
    again = json.loads(sandbox.refreshed_routes(json.dumps(fresh).encode(), plan))
    assert again["identities"] == {}  # an apply between runs scopes nothing to anyone


def test_a_rebuild_that_stopped_stays_pending(root: Path) -> None:
    (root / ".mirror" / "create.json").write_text(
        json.dumps({"last_stage": 4, "hashes": {}, "failed": "stage 5 (Remove setup traces): x"}),
        encoding="utf-8",
    )
    assert _whats(root)[0] == (
        "rebuild",
        "The last rebuild stopped at stage 5 (Remove setup traces): x",
    )


def test_a_world_built_before_these_records_gets_one_once_unchanged(tmp_path: Path) -> None:
    made = portal_fixture.make_project(tmp_path)
    project = load_project(made)
    (made / ".mirror" / "built.json").unlink()
    manifest = _manifest(project)
    (made / ".mirror" / "create.json").write_text(
        json.dumps({"last_stage": 8, "hashes": definition_hash(manifest), "failed": None}),
        encoding="utf-8",
    )
    assert _whats(made) == []  # unchanged since the build: nothing pending
    env.set_visibility(project, "chat", "denied")
    assert _whats(made) == [("next run", "Team chat: visibility granted to denied")]
    # Visibility between granted and denied is not part of what is built, so the next run
    # records the build as unchanged.
    record_applied(project, _manifest(project))
    assert (made / ".mirror" / "built.json").is_file()
    assert _whats(made) == []


def test_a_run_waits_for_a_model_route_added_after_up(root: Path) -> None:
    """Routes reach the gateway and firewall only when the sandbox starts; a run without
    them would leave the agent unable to reach its model, and look like its own failure."""
    from types import SimpleNamespace

    from mirrordimensions.service.runs import _Run  # pyright: ignore[reportPrivateUsage]

    manifest = root / "mirror.yaml"
    text = manifest.read_text(encoding="utf-8")
    route = (
        "models:\n- name: primary\n  provider: anthropic\n  host: api.anthropic.com\n"
        "  credential: {from_env: ANTHROPIC_API_KEY}\n"
    )
    manifest.write_text(
        text.replace("models: []", route, 1) if "models: []" in text else text + route
    )
    assert ("restart", "Model routes changed") in _whats(root)
    run = SimpleNamespace(project=load_project(root))
    with pytest.raises(MirrorError, match="not in effect") as caught:
        _Run._check_nothing_waits(run)  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]
    assert "key set" in str(caught.value)
