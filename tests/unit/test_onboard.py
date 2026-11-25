# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""`mirror agent new`: six steps, drafts that resume, role defaults (build spec, "Onboarding
flows")."""

from __future__ import annotations

from pathlib import Path

import pytest
from ruamel.yaml import YAML
from test_world import manifest  # pyright: ignore[reportMissingImports, reportUnknownVariableType]
from typer.testing import CliRunner

from mirrordimensions.cli.app import app
from mirrordimensions.config.agent import Agent
from mirrordimensions.config.loader import load_model
from mirrordimensions.errors import MirrorError
from mirrordimensions.project import Project
from mirrordimensions.service import onboard
from mirrordimensions.service.project import render_manifest
from mirrordimensions.world.generate import generate, world_json
from mirrordimensions.world.names import suggest_company

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "agents" / "scripted-good"


@pytest.fixture
def project(tmp_path: Path) -> Project:
    text = render_manifest("northfield-ops", suggest_company(48213), 48213)
    (tmp_path / "mirror.yaml").write_text("# The world's definition.\n" + text, encoding="utf-8")
    (tmp_path / ".mirror").mkdir()
    (tmp_path / ".mirror" / "world.json").write_text(
        world_json(generate(manifest())), encoding="utf-8"
    )
    return Project(root=tmp_path)


def agent_file(project: Project, name: str) -> Agent:
    agent, problems = load_model(project.agents_dir / f"{name}.yaml", Agent)
    assert agent is not None, problems
    return agent


def test_the_six_steps_write_a_complete_agent(project: Project) -> None:
    draft = onboard.draft_agent(project, "ops-assistant")
    assert draft.step == 1
    onboard.update_draft(
        project, "ops-assistant", 1, {"mode": "hosted", "image": "ops-assistant:2.4"}
    )
    onboard.update_draft(project, "ops-assistant", 2, {"model": "none"})
    onboard.update_draft(project, "ops-assistant", 3, {"acts_as": {"role": "engineer"}})
    grants = onboard.role_defaults(project, "engineer")
    onboard.update_draft(project, "ops-assistant", 4, {"grants": grants})
    done = onboard.update_draft(
        project,
        "ops-assistant",
        5,
        {"wake": {"type": "command", "command": ["python", "-m", "assistant"]}},
    )
    assert done.step == 6
    agent = agent_file(project, "ops-assistant")
    assert agent.status is None and agent.step is None  # complete: no longer a draft
    assert agent.grants == grants and agent.model is None


def test_a_draft_left_midway_resumes_at_the_same_step(project: Project) -> None:
    onboard.draft_agent(project, "triage")
    onboard.update_draft(project, "triage", 1, {"mode": "browser", "image": "desk-helper:0.9"})
    onboard.update_draft(project, "triage", 2, {"model": "none"})
    resumed = onboard.load_draft(project, "triage")
    assert resumed is not None and resumed.step == 3
    agent = agent_file(project, "triage")
    assert agent.status == "draft" and agent.step == 3 and agent.mode == "browser"
    assert onboard.draft_agent(project, "triage").step == 3  # starting again continues it
    with pytest.raises(MirrorError, match="not answered yet"):
        onboard.update_draft(project, "triage", 5, {"wake": {"type": "poll"}})


def test_role_defaults_come_from_the_company(project: Project) -> None:
    world_text = (project.state_dir / "world.json").read_text(encoding="utf-8")
    grants = onboard.role_defaults(project, "engineer")
    code = next(a.id for a in manifest().apps if a.kind == "code-hosting")
    chat = next(a.id for a in manifest().apps if a.kind == "team-chat")
    repos = grants[code]["repos"]
    assert "write" in repos.values()
    assert all(f'"name": "{r}"' in world_text or f'"{r}"' in world_text for r in repos)
    assert grants[chat]["channels"] and all(isinstance(c, str) for c in grants[chat]["channels"])
    assert onboard.describe_grants(grants)[0].startswith(f"{code}: ")


def test_in_sandbox_models_explain_they_are_not_available(project: Project) -> None:
    with pytest.raises(MirrorError, match="not available yet"):
        onboard.add_model_route(project, "in-sandbox")


def test_a_remote_agent_needs_the_notice_accepted_and_an_mcp_server(project: Project) -> None:
    onboard.draft_agent(project, "vendor")
    with pytest.raises(MirrorError, match="must be accepted first") as info:
        onboard.update_draft(project, "vendor", 1, {"mode": "remote"})
    assert info.value.why == onboard.REMOTE_NOTICE
    # This world has no MCP server: there is no way in for it.
    with pytest.raises(MirrorError, match="no MCP server"):
        onboard.update_draft(
            project, "vendor", 1, {"mode": "remote", "reduced_guarantees": "accepted"}
        )


def test_the_remote_column_writes_a_remote_agent_file(tmp_path: Path) -> None:
    import portal_fixture  # pyright: ignore[reportMissingImports, reportUnknownVariableType]
    from mirrordimensions.service import load_project

    remote = load_project(portal_fixture.make_project(tmp_path))  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
    onboard.draft_agent(remote, "vendor", {"image": "left:1.0"})
    accepted = {"mode": "remote", "reduced_guarantees": "accepted"}
    assert onboard.update_draft(remote, "vendor", 1, accepted).fields.get("image") is None
    onboard.update_draft(remote, "vendor", 2, {"model": "anthropic"})  # ignored: its own
    onboard.update_draft(remote, "vendor", 3, {"acts_as": {"role": "engineer"}})
    defaults = onboard.role_defaults(remote, "engineer", mode="remote")
    assert defaults["tools"] == {}  # every tool: its only way in
    assert "tools" not in onboard.role_defaults(remote, "engineer")
    without = {k: v for k, v in defaults.items() if k != "tools"}
    with pytest.raises(MirrorError, match="must be granted an MCP server"):
        onboard.update_draft(remote, "vendor", 4, {"grants": without})
    onboard.update_draft(remote, "vendor", 4, {"grants": defaults})
    done = onboard.update_draft(remote, "vendor", 5, {"wake": {"type": "poll"}})
    agent = agent_file(remote, "vendor")
    assert done.step == 6 and agent.mode == "remote" and agent.status is None
    assert agent.reduced_guarantees == "accepted"
    assert agent.image is None and agent.model is None and agent.wake is None


def test_the_command_line_shows_the_notice_and_takes_a_flag(tmp_path: Path) -> None:
    import portal_fixture  # pyright: ignore[reportMissingImports, reportUnknownVariableType]

    root = portal_fixture.make_project(tmp_path)  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
    base = ["--project", str(root), "agent", "new", "vendor", "--mode", "remote", "--no-check"]
    refused = CliRunner().invoke(app, base)
    assert refused.exit_code != 0 and "must be accepted first" in str(refused.exception)
    result = CliRunner().invoke(app, [*base, "--accept-reduced-guarantees", "--role", "engineer"])
    assert result.exit_code == 0, result.output
    assert "detected but not blocked" in " ".join(result.output.split())
    assert "the vendor's own" in result.output
    text = (root / "agents" / "vendor.yaml").read_text(encoding="utf-8")  # pyright: ignore[reportUnknownMemberType]
    assert "mode: remote" in text and "reduced_guarantees: accepted" in text and "tools:" in text


def test_a_model_route_is_added_to_mirror_yaml_keeping_its_comments(project: Project) -> None:
    name = onboard.add_model_route(project, "cloud", provider="anthropic")
    text = project.manifest_path.read_text(encoding="utf-8")
    assert text.startswith("# The world's definition.")
    models = YAML(typ="safe").load(text)["models"]  # pyright: ignore[reportUnknownMemberType]
    assert models[-1] == {
        "name": "anthropic",
        "provider": "anthropic",
        "host": "api.anthropic.com",
        "credential": {"from_env": "ANTHROPIC_API_KEY"},
        "hosted_tools": "block",
    }
    assert onboard.add_model_route(project, "cloud", provider="anthropic") == name  # once
    with pytest.raises(MirrorError, match="upstream"):
        onboard.add_model_route(project, "self-hosted", host="llm.northfield.com")
    local = onboard.add_model_route(
        project, "self-hosted", host="llm.northfield.com", upstream="10.20.4.17:8000"
    )
    assert local == "local"


def test_scripted_onboarding_by_flags_alone(project: Project) -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "--project",
            str(project.root),
            "agent",
            "new",
            "ops-assistant",
            "--mode",
            "hosted",
            "--image",
            "ops-assistant:2.4",
            "--build",
            str(EXAMPLE),
            "--model",
            "cloud",
            "--provider",
            "openai",
            "--role",
            "engineer",
            "--grant",
            "code.repos.billing-service=write",
            "--grant",
            "chat.channels=engineering",
            "--wake",
            "command",
            "--command",
            "python -m assistant handle-event",
            "--no-check",
        ],
    )
    assert result.exit_code == 0, result.output
    agent = agent_file(project, "ops-assistant")
    assert agent.model == "openai" and agent.build == EXAMPLE.as_posix()
    assert agent.wake is not None and agent.wake.command == [
        "python",
        "-m",
        "assistant",
        "handle-event",
    ]
    assert agent.grants == {
        "code": {"repos": {"billing-service": "write"}},
        "chat": {"channels": ["engineering"]},
    }


def test_a_browser_agent_by_flags_and_a_resumed_draft(project: Project) -> None:
    runner = CliRunner()
    first = runner.invoke(
        app,
        [
            "--project",
            str(project.root),
            "agent",
            "new",
            "support-triage",
            "--mode",
            "browser",
            "--image",
            "desk-helper:0.9",
            "--model",
            "self-hosted",
            "--model-host",
            "llm.northfield.com",
            "--role",
            "nobody-has-this",
            "--no-check",
        ],
    )
    assert first.exit_code != 0  # step 2 needs --upstream; nothing past step 1 is saved
    draft = onboard.load_draft(project, "support-triage")
    assert draft is not None and draft.step == 2
    second = runner.invoke(
        app,
        [
            "--project",
            str(project.root),
            "agent",
            "new",
            "--resume",
            "support-triage",
            "--model",
            "self-hosted",
            "--model-host",
            "llm.northfield.com",
            "--upstream",
            "10.20.4.17:8000",
            "--role",
            "support",
            "--no-check",
        ],
    )
    assert second.exit_code == 0, second.output
    assert "Continuing support-triage from step 2 of 6" in second.output
    agent = agent_file(project, "support-triage")
    assert agent.mode == "browser" and agent.model == "local"
    assert agent.wake is not None and agent.wake.type == "poll"
    assert agent.acts_as is not None and agent.acts_as.role == "support"
