# SPDX-License-Identifier: Apache-2.0
"""`mirror agent check`: each deliberate misconfiguration produces a failed check that names
its fix (build spec, M4). The engine is replaced by a stand-in; the live checks ran in the
engine (docs/platforms.md)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from ruamel.yaml import YAML
from test_world import manifest  # pyright: ignore[reportMissingImports, reportUnknownVariableType]

from mirrordimensions.engine.docker_api import RunOutput
from mirrordimensions.project import Project
from mirrordimensions.service import agents
from mirrordimensions.service.project import render_manifest
from mirrordimensions.twins.base import Identity
from mirrordimensions.world.generate import generate, world_json
from mirrordimensions.world.names import suggest_company

BUNDLE = b"-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----\n"


class FakeDocker:
    def __init__(self) -> None:
        self.arch = "arm64"
        self.running = True
        self.bundle: bytes | None = BUNDLE
        self.model_status = "200"

    def is_running(self, name: str) -> bool:
        return self.running

    def info(self) -> dict[str, Any]:
        return {"Architecture": "aarch64"}

    def image_arch(self, image: str) -> str | None:
        return self.arch

    def create(self, spec: Any) -> None: ...
    def start(self, name: str) -> None: ...
    def remove(self, name: str) -> None: ...
    def put_files(self, name: str, files: Any) -> None: ...
    def pull(self, image: str, platform: str | None = None) -> None: ...

    def read_file(self, name: str, path: str) -> bytes | None:
        return self.bundle if path == "/etc/ssl/certs/ca-certificates.crt" else None

    def run(self, image: str, command: list[str], **_: Any) -> RunOutput:
        return RunOutput(exit_code=0, output=self.model_status)


IDS = {
    "code": Identity(
        username="ana.silva",
        password="pw",
        token="t1",
        env={"GITEA_URL": "https://git.northfield.com", "GITEA_TOKEN": "t1"},
    )
}


@pytest.fixture
def docker(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> FakeDocker:
    fake = FakeDocker()
    monkeypatch.setattr(agents, "_docker", lambda: (fake, "lima", "dedicated-vm", 0.0))
    world = generate(manifest())
    person = next(p for p in world.people if "engineer" in p.roles and p.left_ago is None)
    monkeypatch.setattr(agents, "issue", lambda project, agent, d=None: (person, IDS))
    return fake


@pytest.fixture
def project(tmp_path: Path) -> Project:
    text = render_manifest("northfield-ops", suggest_company(48213), 48213)
    data = YAML(typ="safe").load(text)  # pyright: ignore[reportUnknownMemberType]
    data["models"] = [
        {
            "name": "ops",
            "provider": "self-hosted",
            "host": "llm.northfield.com",
            "upstream": "10.20.4.17:8000",
            "credential": {"from_env": "OPS_LLM_KEY"},
        }
    ]
    yaml = YAML()
    with (tmp_path / "mirror.yaml").open("w", encoding="utf-8") as handle:
        yaml.dump(data, handle)  # pyright: ignore[reportUnknownMemberType]
    (tmp_path / ".mirror" / "ca").mkdir(parents=True)
    (tmp_path / ".mirror" / "ca" / "root-ca.crt").write_bytes(BUNDLE)
    (tmp_path / ".mirror" / "world.json").write_text(
        world_json(generate(manifest())), encoding="utf-8"
    )
    (tmp_path / "agents").mkdir()
    return Project(root=tmp_path)


def write_agent(project: Project, **changes: Any) -> None:
    code = next(a.id for a in manifest().apps if a.kind == "code-hosting")
    agent: dict[str, Any] = {
        "name": "ops-assistant",
        "mode": "hosted",
        "image": "ops-assistant:2.4",
        "acts_as": {"role": "engineer"},
        "wake": {"type": "poll"},
        "grants": {code: {"repos": {"billing-service": "write"}}},
    }
    agent.update(changes)
    agent = {k: v for k, v in agent.items() if v is not None}
    with (project.agents_dir / "ops-assistant.yaml").open("w", encoding="utf-8") as handle:
        YAML().dump(agent, handle)  # pyright: ignore[reportUnknownMemberType]


def failed(project: Project, **kwargs: Any) -> list[agents.PreflightCheck]:
    checks = agents.check_agent(project, "ops-assistant", **kwargs)
    bad = [c for c in checks if c.outcome == "fail"]
    for check in bad:
        assert check.fix, f"{check.name} failed without naming its fix"
    return bad


@pytest.fixture(autouse=True)
def model_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPS_LLM_KEY", "sk-ops-1")


def test_a_well_formed_agent_passes(project: Project, docker: FakeDocker) -> None:
    write_agent(project)
    assert failed(project) == []
    outcomes = {c.name: c.outcome for c in agents.check_agent(project, "ops-assistant")}
    assert outcomes["The model is reachable through its route: ops"] == "pass"
    assert outcomes["Provider-hosted tools: ops"] == "pass"
    assert list(outcomes.values()).count("pass") == len(outcomes)  # nothing skipped


@pytest.mark.parametrize(
    ("change", "setup", "check", "fix_mentions"),
    [
        (
            {"status": "draft", "step": 3, "wake": None},
            None,
            "The agent file is complete",
            "--resume",
        ),
        ({}, "stopped", "The world is running", "mirror up"),
        ({}, "amd64", "The image is built for the engine", "--allow-emulated"),
        ({}, "no-bundle", "root trusted", "ca-certificates"),
        ({"env": {"API": "http://127.0.0.1:8080"}}, None, "operator's tools", "host"),
        ({"env": {"CHAT": "${chat.token}"}}, None, "variables are filled", "grant"),
        ({"model": "nowhere"}, None, "model is reachable", "mirror.yaml"),
        ({}, "no-key", "model is reachable", "OPS_LLM_KEY"),
        ({}, "refused", "model is reachable", "OPS_LLM_KEY"),
        ({}, "unreachable", "model is reachable", "mirror up"),
    ],
)
def test_each_misconfiguration_fails_with_its_fix(
    project: Project,
    docker: FakeDocker,
    monkeypatch: pytest.MonkeyPatch,
    change: dict[str, Any],
    setup: str | None,
    check: str,
    fix_mentions: str,
) -> None:
    write_agent(project, **change)
    if setup == "stopped":
        docker.running = False
    elif setup == "amd64":
        docker.arch = "amd64"
    elif setup == "no-bundle":
        docker.bundle = None
    elif setup == "no-key":
        monkeypatch.delenv("OPS_LLM_KEY")
    elif setup == "refused":
        docker.model_status = "401"
    elif setup == "unreachable":
        docker.model_status = "000"
    bad = failed(project)
    assert len(bad) == 1, [c.name for c in bad]
    assert check in bad[0].name
    assert fix_mentions in bad[0].fix


def test_allow_emulated_turns_the_architecture_failure_into_reduced(
    project: Project, docker: FakeDocker
) -> None:
    write_agent(project)
    docker.arch = "amd64"
    checks = agents.check_agent(project, "ops-assistant", allow_emulated=True)
    image = next(c for c in checks if c.name == "The image is built for the engine")
    assert image.outcome == "pass" and "reduced isolation" in image.detail
