# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""Worlds on this machine and the world wizard, for the portal (decision 0022).

The portal serves one world at a time. Its wizard defines a new one in a folder the admin
chooses (next to the current world by default) with the same answers and the same
`mirror.yaml` as `mirror world new`, then creates it and switches to it. Every world shares
the one engine, so creating a world stops whichever world's sandbox is running.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, cast

from pydantic import BaseModel, Field
from ruamel.yaml import YAML

from mirrordimensions.errors import MirrorError
from mirrordimensions.project import MANIFEST, Project
from mirrordimensions.service import worlddef
from mirrordimensions.world.names import CompanySuggestion, slug, suggest_company


class WorldEntry(BaseModel):
    folder: str
    name: str
    company: str
    state: str = Field(description="draft, defined, creating, ready, stale or failed")
    current: bool


class SystemPreview(BaseModel):
    id: str
    kind: str
    product: str | None
    hostname: str
    note: str = Field(description="Empty when it will be built; why not, otherwise")


class WorldDraftView(BaseModel):
    folder: str
    step: int
    draft: worlddef.Draft
    company: CompanySuggestion = Field(description="The company as it stands, suggested if open")
    systems: list[SystemPreview]
    yaml: str = Field(description="mirror.yaml as it will be written")
    templates: list[worlddef.Template]
    command: str = Field(description="The same definition from the command line")


def _state(root: Path) -> str:
    if worlddef.draft_path(root).is_file():
        return "draft"
    return worlddef.world_status(Project(root=root)).state


def list_worlds(current: Project) -> list[WorldEntry]:
    """The current world and every world beside it (folders holding a mirror.yaml)."""
    here = current.root.resolve()
    seen: dict[Path, WorldEntry] = {}
    for folder in sorted([here, *(p for p in here.parent.iterdir() if p.is_dir())]):
        if folder in seen or not (folder / MANIFEST).is_file():
            continue
        try:
            text = (folder / MANIFEST).read_text("utf-8")
            data: dict[str, Any] = YAML(typ="safe").load(text) or {}  # pyright: ignore[reportUnknownMemberType]
        except Exception:  # noqa: BLE001 (an unreadable file is listed by its folder)
            data = {}
        company = cast(dict[str, Any], data.get("company") or {})
        seen[folder] = WorldEntry(
            folder=str(folder),
            name=str(data.get("name") or folder.name),
            company=str(company.get("name") or ""),
            state=_state(folder),
            current=folder == here,
        )
    return sorted(seen.values(), key=lambda w: (not w.current, w.name))


def resolve_folder(current: Project, folder: str) -> Path:
    """A folder the admin typed: absolute, or a name beside the current world."""
    text = folder.strip()
    if not text:
        raise MirrorError("Name a folder for the new world.", "", "Type a name, such as acme-ops.")
    path = Path(text).expanduser()
    if not path.is_absolute():
        if "/" in text or "\\\\" in text or text in (".", ".."):
            raise MirrorError(
                f"{text!r} is not a folder name.",
                "A relative name is created beside the current world.",
                "Type a plain name, or a full path.",
            )
        path = current.root.resolve().parent / text
    return path.resolve()


def _view(root: Path, draft: worlddef.Draft) -> WorldDraftView:
    company = draft.company or suggest_company(draft.seed, attempt=draft.attempt)
    shown = draft.model_copy(update={"company": company})
    text = worlddef.render_world(root, shown, status="draft")
    data: dict[str, Any] = YAML(typ="safe").load(text) or {}  # pyright: ignore[reportUnknownMemberType]
    systems: list[SystemPreview] = []
    for app in cast(list[dict[str, Any]], data.get("apps") or []):
        systems.append(
            SystemPreview(
                id=str(app["id"]),
                kind=str(app.get("kind") or ""),
                product=app.get("product"),
                hostname=str(app["hostname"]),
                note=(
                    "No twin yet: recorded, not created"
                    if app.get("build") == "unavailable"
                    else ""
                ),
            )
        )
    for line in text.splitlines():
        if line.strip().startswith("# ") and "not in the catalog" in line:
            query = line.strip()[2:].split(":")[0]
            systems.append(
                SystemPreview(
                    id=slug(query),
                    kind="",
                    product=None,
                    hostname="",
                    note="Not in the catalog: left out",
                )
            )
    return WorldDraftView(
        folder=str(root),
        step=draft.step,
        draft=draft,
        company=company,
        systems=systems,
        yaml=text,
        templates=worlddef.list_templates(),
        command=command_for(root, shown),
    )


def command_for(root: Path, draft: worlddef.Draft) -> str:
    """The `mirror world new` command that writes the same mirror.yaml."""
    company = draft.company or suggest_company(draft.seed, attempt=draft.attempt)
    parts = [f"mirror world new {root.name}", f"--seed {draft.seed}"]
    if draft.systems and not draft.template:
        parts.append(f"--systems {','.join(draft.systems)}")
    else:
        parts.append(f"--template {draft.template or 'software-team'}")
    parts.append(f'--company "{company.name}" --domain {company.domain}')
    parts.append(f"--industry {company.industry}")
    parts.append(f"--people {draft.people or 25} --history {draft.history or 180}")
    if draft.tidiness != "realistic":
        parts.append(f"--tidiness {draft.tidiness}")
    data = {**worlddef.DATA_DEFAULTS, **draft.data}
    parts += [f"--{k} {v}" for k, v in data.items() if v != worlddef.DATA_DEFAULTS[k]]
    links = {**worlddef.LINK_DEFAULTS, **draft.links}
    parts += [f"--no-{k}" for k, on in links.items() if not on]
    return " ".join(parts)


def open_draft(current: Project, folder: str) -> WorldDraftView:
    """Start the wizard in a folder, or continue the draft already there."""
    root = resolve_folder(current, folder)
    if (root / MANIFEST).is_file() and not worlddef.draft_path(root).is_file():
        raise MirrorError(
            f"{root} already holds a world.",
            "The wizard defines a new world in an empty folder, or continues a draft.",
            "Choose another folder, or switch to that world.",
        )
    return _view(root, worlddef.load_draft(root))


class DraftFields(BaseModel):
    """One step's answers. Fields left out keep their value."""

    template: str | None = None
    systems: list[str] | None = None
    company_name: str | None = None
    domain: str | None = None
    industry: str | None = None
    another_company: bool = False
    people: int | None = Field(default=None, ge=2, le=2000)
    history: int | None = Field(default=None, ge=7, le=3650)
    tidiness: Literal["tidy", "realistic", "messy"] | None = None
    links: dict[str, bool] | None = None
    data: dict[str, int] | None = None
    seed: int | None = Field(default=None, ge=1)
    step: int | None = Field(default=None, ge=1, le=6)


def update_draft(current: Project, folder: str, fields: DraftFields) -> WorldDraftView:
    """Save one step's answers: draft.json, and mirror.yaml as it now stands."""
    root = resolve_folder(current, folder)
    draft = worlddef.load_draft(root)
    if fields.template is not None:
        if fields.template not in worlddef.TEMPLATES:
            raise MirrorError(
                f"Unknown template {fields.template!r}.",
                f"Templates: {', '.join(worlddef.TEMPLATES)}.",
                "",
            )
        draft.template, draft.systems = fields.template, None
    if fields.systems is not None:
        names = [n.strip() for n in fields.systems if n.strip()]
        if not names:
            raise MirrorError("Name at least one system.", "", "Such as: gitea, mattermost")
        draft.systems, draft.template = names, None
    if fields.seed is not None and fields.seed != draft.seed:
        draft.seed, draft.attempt, draft.company = fields.seed, 0, None
    if fields.another_company:
        draft.attempt += 1
        draft.company = suggest_company(draft.seed, attempt=draft.attempt)
    if fields.company_name or fields.domain or fields.industry:
        base = draft.company or suggest_company(draft.seed, attempt=draft.attempt)
        name = (fields.company_name or base.name).strip()
        if fields.domain:
            domain = fields.domain.strip().lower()
        elif fields.company_name:
            domain = f"{slug(name)}.com"  # a new name brings a matching domain
        else:
            domain = base.domain
        if "." not in domain or " " in domain:
            raise MirrorError(f"{domain!r} is not a domain.", "It needs a dot, like acme.com.", "")
        draft.company = CompanySuggestion(
            name=name, domain=domain, industry=(fields.industry or base.industry).strip()
        )
    for key in ("people", "history", "tidiness"):
        value = getattr(fields, key)
        if value is not None:
            setattr(draft, key, value)
    if fields.links is not None:
        draft.links = {
            **worlddef.LINK_DEFAULTS,
            **{k: bool(v) for k, v in fields.links.items() if k in worlddef.LINK_DEFAULTS},
        }
    if fields.data is not None:
        for key, value in fields.data.items():
            if key not in worlddef.DATA_DEFAULTS or not 0 <= int(value) <= 100_000:
                raise MirrorError(f"{key}: {value} is not a count this world can hold.", "", "")
        draft.data = {**worlddef.DATA_DEFAULTS, **draft.data, **fields.data}
    if fields.step is not None:
        draft.step = max(draft.step, fields.step)
    if draft.company is None and draft.step >= 2:
        draft.company = suggest_company(draft.seed, attempt=draft.attempt)
    worlddef.save_draft(root, draft)
    return _view(root, draft)


def finish(current: Project, folder: str) -> Path:
    """Write the definition (`status: defined`) and the world's own files."""
    root = resolve_folder(current, folder)
    draft = worlddef.load_draft(root)
    draft.company = draft.company or suggest_company(draft.seed, attempt=draft.attempt)
    draft.people = draft.people or 25
    draft.history = draft.history or 180
    if draft.template is None and not draft.systems:
        draft.template = "software-team"
    return worlddef.finish_draft(root, draft)
