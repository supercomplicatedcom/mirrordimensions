# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""World definition: start a definition from a template or named systems, show it, clone it,
and report its state (build spec, "World definition and creation")."""

from __future__ import annotations

import hashlib
import json
import secrets
import shutil
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from mirrordimensions.catalog.index import match_systems
from mirrordimensions.config.loader import load_model
from mirrordimensions.config.manifest import Manifest
from mirrordimensions.errors import MirrorError
from mirrordimensions.hostos.files import make_dir, write_text
from mirrordimensions.network.ca import create_root_ca
from mirrordimensions.project import MANIFEST, STATE_DIR, Project
from mirrordimensions.service.project import PROJECT_GITIGNORE, render_manifest
from mirrordimensions.world.names import CompanySuggestion, slug, suggest_company

TEMPLATES = {"software-team": "Code hosting and team chat for a small software organization"}
HOSTNAME_PREFIX = {
    "code-hosting": "git",
    "team-chat": "chat",
    "ticketing": "tickets",
    "wiki": "wiki",
    "crm": "crm",
    "hr": "hr",
    "helpdesk": "help",
    "identity": "sso",
}
WorldState = Literal["draft", "defined", "creating", "ready", "stale", "failed"]
SNAPSHOT_STAGE = 6  # "Save the base snapshot": from here the world is built as defined
STAGES = [
    "Generate the company",
    "Set up the sealed network",
    "Start each system",
    "Load each system",
    "Remove setup traces",
    "Save the base snapshot",
    "Run checks",
    "Ready",
]


class Template(BaseModel):
    name: str
    description: str


class WorldStatus(BaseModel):
    state: WorldState
    last_stage: int
    stages: list[str]
    definition_changed: bool
    unavailable: list[str]


def list_templates() -> list[Template]:
    return [Template(name=n, description=d) for n, d in TEMPLATES.items()]


def suggest(seed: int, industry: str | None = None, attempt: int = 0) -> CompanySuggestion:
    return suggest_company(seed, industry, attempt)


def definition_hash(manifest: Manifest) -> dict[str, str]:
    """Hashes of the parts of a definition, so a change re-runs only the stages it affects."""

    def h(value: Any) -> str:
        return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()[
            :12
        ]

    # Visibility between granted, denied and present takes effect at the next run, like
    # rules; only which systems are absent changes what is built (decision 0021).
    systems = [a.model_dump(exclude={"rules", "visibility"}) for a in manifest.apps]
    return {
        "company": h(manifest.company.model_dump()),
        "systems": h(systems),
        # Systems left out of the build: one brought back needs building; one left out
        # later only needs the sandbox restarted, since its data is in the snapshot.
        "absent": ",".join(sorted(a.id for a in manifest.apps if a.visibility == "absent")),
        # How "systems" was hashed before, so a world built then is not taken for stale.
        "systems_v1": h([a.model_dump(exclude={"rules"}) for a in manifest.apps]),
        "data": h(manifest.data.model_dump() if manifest.data else None),
        "rules": h([[r.model_dump() for r in a.rules] for a in manifest.apps]),
        "visibility": h({a.id: a.visibility for a in manifest.apps}),
    }


def first_stage_affected(old: dict[str, str], new: dict[str, str]) -> int:
    """1-based stage to resume from: company -> 1, systems -> 2, data -> 4, rules -> none (9)."""
    if old.get("company") != new["company"]:
        return 1
    if "absent" in old:
        if old.get("systems") != new["systems"]:
            return 2
        was_absent = set(filter(None, str(old["absent"]).split(",")))
        if was_absent - set(filter(None, new.get("absent", "").split(","))):
            return 2  # a system the world was built without is wanted now
    elif old.get("systems") not in (new["systems"], new.get("systems_v1")):
        return 2  # recorded before "absent" was kept: visibility was in the systems hash
    if old.get("data") != new["data"]:
        return 4
    return 9


def resume_stage(
    record: dict[str, Any], hashes: dict[str, str], resume: bool, from_stage: int | None
) -> int:
    """The 1-based stage to start at. Without --resume a recorded world starts over; with it,
    the earlier of the first unfinished stage and the first stage a change affects."""
    if from_stage is not None:
        if not 1 <= from_stage <= len(STAGES):
            raise MirrorError(
                f"There is no stage {from_stage}.",
                f"Stages are 1 to {len(STAGES)}.",
                "Run: mirror world status",
            )
        return from_stage
    if not record:
        return 1
    affected = first_stage_affected(record.get("hashes", {}), hashes)
    if not resume:
        return (
            1
            if record.get("failed") or int(record.get("last_stage", 0)) < len(STAGES)
            else affected
        )
    return min(int(record.get("last_stage", 0)) + 1, affected)


class Draft(BaseModel):
    """Answers so far to `mirror world new`, kept so an interrupted session resumes."""

    seed: int
    attempt: int = 0
    company: CompanySuggestion | None = None
    template: str | None = None
    systems: list[str] | None = None
    people: int | None = None
    history: int | None = None


QUESTIONS = ("company", "shape", "people", "history")


def draft_path(root: Path) -> Path:
    return root.resolve() / STATE_DIR / "draft.json"


def load_draft(root: Path) -> Draft:
    path = draft_path(root)
    if path.is_file():
        return Draft.model_validate_json(path.read_text(encoding="utf-8"))
    return Draft(seed=secrets.randbelow(900_000) + 100_000)


def save_draft(root: Path, draft: Draft) -> None:
    make_dir(draft_path(root).parent, owner_only=True)
    write_text(draft_path(root), draft.model_dump_json(indent=2) + "\n", owner_only=True)


def next_question(draft: Draft) -> str | None:
    """The first question not yet answered, or None when the draft is complete."""
    if draft.company is None:
        return "company"
    if draft.template is None and not draft.systems:
        return "shape"
    if draft.people is None:
        return "people"
    if draft.history is None:
        return "history"
    return None


def finish_draft(root: Path, draft: Draft) -> Path:
    if next_question(draft) is not None:
        raise MirrorError(
            "The draft is not complete.",
            f"Still to answer: {next_question(draft)}.",
            "Run: mirror world new",
        )
    made = new_world(
        root,
        draft.template,
        draft.systems,
        draft.people or 25,
        draft.history or 180,
        draft.seed,
        company=draft.company,
    )
    draft_path(root).unlink(missing_ok=True)
    return made


def new_world(
    path: Path,
    template: str | None = None,
    systems: list[str] | None = None,
    people: int = 25,
    history: int = 180,
    seed: int | None = None,
    industry: str | None = None,
    company: CompanySuggestion | None = None,
) -> Path:
    """Write a definition: a template, or named systems matched against the catalog."""
    root = path.resolve()
    if (root / MANIFEST).exists():
        raise MirrorError(
            f"{root} already holds a world.", f"{MANIFEST} exists there.", "Choose another folder."
        )
    if template is None and not systems:
        template = "software-team"
    if template is not None and template not in TEMPLATES:
        raise MirrorError(
            f"Unknown template {template!r}.",
            f"Templates: {', '.join(TEMPLATES)}.",
            "Run: mirror world new --template software-team",
        )
    seed = seed if seed is not None else secrets.randbelow(900_000) + 100_000
    company = company or suggest_company(seed, industry)
    text = render_manifest(slug(root.name) or slug(company.name), company, seed)
    text = text.replace("  size: 25\n", f"  size: {people}\n").replace(
        "  history_days: 180\n", f"  history_days: {history}\n"
    )
    if systems:
        apps: list[str] = []
        for i, match in enumerate(match_systems(systems)):
            if match.entry is None:
                apps.append(f"  # {match.query}: not in the catalog; left out\n")
                continue
            e = match.entry
            host = f"{HOSTNAME_PREFIX.get(e.kind, slug(e.name)[:12])}.{company.domain}"
            line = f"  - id: {slug(e.kind)[:20] or f'app{i}'}\n    kind: {e.kind}\n    product: {e.slug}\n    hostname: {host}\n    visibility: granted\n"
            if not match.buildable:
                line += "    build: unavailable    # no twin yet: recorded, not created\n"
            apps.append(line)
        start = text.index("apps:\n") + len("apps:\n")
        end = text.index("links:\n")
        text = text[:start] + "".join(apps) + text[end:]
    make_dir(root)
    write_text(root / MANIFEST, text)
    write_text(root / ".gitignore", PROJECT_GITIGNORE)
    make_dir(root / "agents")
    make_dir(root / STATE_DIR, owner_only=True)
    create_root_ca(root / STATE_DIR / "ca", company.name, seed)
    load = load_model(root / MANIFEST, Manifest)
    if load[0] is None:
        raise MirrorError(
            "The new definition is not valid.", load[1][0].render(), "Report this as a bug."
        )
    return root


def world_status(project: Project) -> WorldStatus:
    manifest, problems = load_model(project.manifest_path, Manifest)
    if manifest is None:
        return WorldStatus(
            state="draft",
            last_stage=0,
            stages=STAGES,
            definition_changed=False,
            unavailable=[p.message for p in problems[:3]],
        )
    unavailable = [a.id for a in manifest.apps if a.build == "unavailable"]
    path = project.state_dir / "create.json"
    record: dict[str, Any] = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    last = int(record.get("last_stage", 0))
    changed = (
        bool(record)
        and first_stage_affected(record.get("hashes", {}), definition_hash(manifest)) <= 8
    )
    if record.get("failed"):
        state: WorldState = "failed"
    elif changed:
        state = "stale"
    elif last >= 8:
        state = "ready"
    elif last > 0:
        state = "creating"
    else:
        state = "defined" if manifest.status == "defined" else "draft"
    return WorldStatus(
        state=state,
        last_stage=last,
        stages=STAGES,
        definition_changed=changed,
        unavailable=unavailable,
    )


def record_stage(
    project: Project, stage: int, manifest: Manifest, failed: str | None = None
) -> None:
    path = project.state_dir / "create.json"
    record = {"last_stage": stage, "hashes": definition_hash(manifest), "failed": failed}
    write_text(path, json.dumps(record, indent=2) + "\n", owner_only=True)
    if failed is None and stage == SNAPSHOT_STAGE:
        from mirrordimensions.service.changes import record_built

        record_built(project, manifest)


def clone_world(src: Path, dst: Path, new_seed: bool = False) -> Path:
    """Copy a definition (never its state). With a new seed, the same shape, another company."""
    source = Project(root=src.resolve())
    manifest, problems = load_model(source.manifest_path, Manifest)
    if manifest is None:
        raise MirrorError(
            "The source definition is not valid.", problems[0].render(), "Run: mirror validate"
        )
    root = dst.resolve()
    if (root / MANIFEST).exists():
        raise MirrorError(
            f"{root} already holds a world.", f"{MANIFEST} exists there.", "Choose another folder."
        )
    text = source.manifest_path.read_text(encoding="utf-8")
    seed = manifest.company.seed
    if new_seed:
        seed = secrets.randbelow(900_000) + 100_000
        company = suggest_company(seed, manifest.company.industry)
        old = manifest.company
        text = (
            text.replace(f"seed: {old.seed}", f"seed: {seed}")
            .replace(old.domain, company.domain)
            .replace(old.name, company.name)
        )
    make_dir(root)
    write_text(root / MANIFEST, text)
    write_text(root / ".gitignore", PROJECT_GITIGNORE)
    if (source.root / "agents").is_dir():
        shutil.copytree(source.root / "agents", root / "agents", dirs_exist_ok=True)
    make_dir(root / STATE_DIR, owner_only=True)
    new_manifest, _ = load_model(root / MANIFEST, Manifest)
    create_root_ca(
        root / STATE_DIR / "ca",
        new_manifest.company.name if new_manifest else manifest.company.name,
        seed,
    )
    return root


def show_world(project: Project) -> dict[str, Any]:
    manifest, problems = load_model(project.manifest_path, Manifest)
    if manifest is None:
        raise MirrorError(
            "mirror.yaml is not valid.",
            problems[0].render() if problems else "",
            "Run: mirror validate",
        )
    c = manifest.company
    return {
        "company": f"{c.name} ({c.domain}), {c.industry}, {c.size} people, {c.history_days} days of history, {c.tidiness} data, seed {c.seed}",
        "systems": [
            f"{a.id}: {a.product or a.kind} at {a.hostname}"
            + (" (unavailable: no twin yet)" if a.build == "unavailable" else "")
            for a in manifest.apps
        ],
        "links": [f"{k}: {v}" for link in manifest.links for k, v in link.items()],
        "data": manifest.data.model_dump(exclude_none=True) if manifest.data else {},
    }
