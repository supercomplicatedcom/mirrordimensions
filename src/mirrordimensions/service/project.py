# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""Create, load, validate and describe a project."""

from __future__ import annotations

import secrets
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from mirrordimensions import plugins
from mirrordimensions.config.agent import Agent
from mirrordimensions.config.common import duplicates_ignoring_case
from mirrordimensions.config.loader import Problem, line_in, load_model
from mirrordimensions.config.manifest import Manifest
from mirrordimensions.config.result import PluginRef
from mirrordimensions.config.scenario import Scenario
from mirrordimensions.errors import MirrorError
from mirrordimensions.hostos.files import make_dir, write_text
from mirrordimensions.hostos.info import HostInfo, host_info
from mirrordimensions.network.ca import create_root_ca
from mirrordimensions.project import MANIFEST, STATE_DIR, Project, find_project
from mirrordimensions.world import denylist
from mirrordimensions.world.names import CompanySuggestion, slug, suggest_company

PROJECT_GITIGNORE = "# Generated state: certificates, snapshots, runs. Never commit it.\n.mirror/\n"


class InitResult(BaseModel):
    root: Path
    name: str
    company: CompanySuggestion
    seed: int
    ca_subject: str
    created: list[str]


def render_manifest(name: str, company: CompanySuggestion, seed: int) -> str:
    """The starter manifest: the software-team shape, with code hosting and chat."""
    d = company.domain
    return f"""\
# Environment manifest: the single source of truth for this world.
# Check it with: mirror validate
version: 1
name: {name}
company:
  name: {company.name}
  domain: {d}
  industry: {company.industry}
  size: 25
  history_days: 180
  tidiness: realistic
  seed: {seed}
apps:
  - id: code
    kind: code-hosting
    product: gitea
    hostname: git.{d}
    visibility: granted
  - id: chat
    kind: team-chat
    product: mattermost
    hostname: chat.{d}
    visibility: granted
links:
  - announce: {{from: code, to: chat, channel: engineering}}
  - incidents: {{in: [chat, code]}}
data:
  repositories: 6
  issues: 150
  messages: 2000
  canaries: 3
models: []    # model routes are added when an agent is onboarded
isolation:
  runtime: auto
"""


def init_project(
    path: Path,
    name: str | None = None,
    seed: int | None = None,
    industry: str | None = None,
) -> InitResult:
    """Create a project: starter manifest, agents folder, root CA, and a .gitignore."""
    root = path.resolve()
    if (root / MANIFEST).exists():
        raise MirrorError(
            f"{root} already holds a project.",
            f"{MANIFEST} exists there.",
            "Choose another folder, or edit the existing manifest.",
        )
    if seed is None:
        seed = secrets.randbelow(900_000) + 100_000
    company = suggest_company(seed, industry)
    project_name = (slug(name or root.name) or slug(company.name))[:63].rstrip("-")
    if not project_name or not project_name[0].isalpha():
        project_name = slug(company.name)
    for text in (company.name, company.domain):
        found = denylist.findings(text)
        if found:  # cannot happen with the built-in lists; guards future edits to them
            raise MirrorError(
                "The generated company name contains a word that gives the test away.",
                f"{text!r} contains {', '.join(found)}.",
                "Run mirror init again with another --seed.",
            )

    created: list[str] = []
    make_dir(root)
    write_text(root / MANIFEST, render_manifest(project_name, company, seed))
    created.append(MANIFEST)
    make_dir(root / "agents")
    created.append("agents/")
    write_text(root / ".gitignore", PROJECT_GITIGNORE)
    created.append(".gitignore")
    make_dir(root / STATE_DIR, owner_only=True)
    ca = create_root_ca(root / STATE_DIR / "ca", company.name, seed)
    created.append(".mirror/ca/")
    return InitResult(
        root=root,
        name=project_name,
        company=company,
        seed=seed,
        ca_subject=ca.subject,
        created=created,
    )


def load_project(path: Path) -> Project:
    return find_project(path)


def _rel(project: Project, path: Path) -> str:
    return path.relative_to(project.root).as_posix()


def validate(project: Project) -> list[Problem]:
    """Every problem in the manifest, agent files and scenarios, with file and line."""
    problems: list[Problem] = []
    manifest, found = load_model(project.manifest_path, Manifest)
    problems += [p.model_copy(update={"file": MANIFEST}) for p in found]
    app_ids = {a.id for a in manifest.apps} if manifest else set[str]()
    if manifest is not None:
        from mirrordimensions.service.systems import validate_rule

        for app in manifest.apps:
            for rule in app.rules:
                for message in validate_rule(app, rule.model_dump(exclude_none=True)):
                    problems.append(
                        Problem(
                            file=MANIFEST,
                            line=line_in(project.manifest_path, ("apps",)),
                            message=message,
                        )
                    )

    def files(folder: Path) -> list[Path]:
        if not folder.is_dir():
            return []
        listed = sorted([*folder.glob("*.yaml"), *folder.glob("*.yml")])
        for dupe in duplicates_ignoring_case([p.name for p in listed]):
            problems.append(
                Problem(
                    file=_rel(project, folder / dupe),
                    message="another file has the same name ignoring case; "
                    "macOS and Windows cannot hold both",
                )
            )
        return listed

    agent_names: list[tuple[str, str]] = []
    for path in files(project.agents_dir):
        agent, found = load_model(path, Agent)
        problems += [p.model_copy(update={"file": _rel(project, path)}) for p in found]
        if agent is None:
            continue
        agent_names.append((agent.name, _rel(project, path)))
        if manifest is not None:
            for app_id in agent.grants:
                if app_id not in app_ids:
                    problems.append(
                        Problem(
                            file=_rel(project, path),
                            line=line_in(path, ("grants", app_id)),
                            message=f"grants: {app_id!r} is not an app in {MANIFEST} "
                            f"(apps: {', '.join(sorted(app_ids)) or 'none'})",
                        )
                    )
    for dupe in duplicates_ignoring_case([n for n, _ in agent_names]):
        where = [f for n, f in agent_names if n.casefold() == dupe.casefold()]
        problems.append(
            Problem(file=where[-1], message=f"agent name {dupe!r} is also used in {where[0]}")
        )

    scenario_ids: list[tuple[str, str]] = []
    for path in files(project.scenarios_dir):
        scenario, found = load_model(path, Scenario)
        problems += [p.model_copy(update={"file": _rel(project, path)}) for p in found]
        if scenario is not None:
            scenario_ids.append((scenario.id, _rel(project, path)))
    for dupe in duplicates_ignoring_case([i for i, _ in scenario_ids]):
        where = [f for i, f in scenario_ids if i.casefold() == dupe.casefold()]
        problems.append(
            Problem(file=where[-1], message=f"scenario id {dupe!r} is also used in {where[0]}")
        )
    return problems


ProjectState = Literal["none", "new", "built", "up", "running", "stale"]


class Status(BaseModel):
    project: Path | None
    name: str | None
    state: ProjectState
    valid: bool | None
    problems: int
    host: HostInfo
    plugins: list[PluginRef]


def status(start: Path) -> Status:
    """Derived on every call from files (and, from M0.5, the engine). Never stored."""
    host = host_info()
    found = plugins.discover()
    try:
        project = find_project(start)
    except MirrorError:
        return Status(
            project=None, name=None, state="none", valid=None, problems=0, host=host, plugins=found
        )
    manifest, _ = load_model(project.manifest_path, Manifest)
    problems = validate(project)
    # Until the world generator exists (M3), a project is always "new".
    state: ProjectState = "built" if (project.state_dir / "world.json").exists() else "new"
    return Status(
        project=project.root,
        name=manifest.name if manifest else None,
        state=state,
        valid=not problems,
        problems=len(problems),
        host=host,
        plugins=found,
    )
