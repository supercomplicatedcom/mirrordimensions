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
from mirrordimensions.service import imports, worlddef
from mirrordimensions.service.changes import Change
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
    imported: imports.ImportReview | None = Field(
        default=None, description="The import in this folder, when the world starts from one"
    )
    proposal: worlddef.Proposal | None = Field(
        default=None,
        description="The systems the company's industry usually runs, while the world still "
        "starts from the template (decision 0028, point 3)",
    )


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
    review = imports.peek_import(Project(root=root)) if draft.imported else None
    if review is not None and draft.company is not None and (root / MANIFEST).is_file():
        text = (root / MANIFEST).read_text(encoding="utf-8")  # with the import applied
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
                    else f"Runs in place of {app['in_place_of']}, which has no twin yet"
                    if app.get("in_place_of")
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
        imported=review,
        proposal=(
            worlddef.propose(company.industry, draft.substitute)
            if not draft.imported and not draft.systems
            else None
        ),
    )


def command_for(root: Path, draft: worlddef.Draft) -> str:
    """The `mirror world new` command that writes the same mirror.yaml."""
    company = draft.company or suggest_company(draft.seed, attempt=draft.attempt)
    parts = [f"mirror world new {root.name}", f"--seed {draft.seed}"]
    if draft.imported:
        found = imports.peek_import(Project(root=root))
        loaded = imports.load_draft(Project(root=root))
        # Forward slashes: every shell reads them, and so does Windows.
        shown = (
            [Path(s.path).as_posix() if s.path else s.file for s in found.sources] if found else []
        )
        parts += [f"--import {_quote(p)}" for p in shown]
        if loaded is not None:
            chosen = {**loaded.decisions, **loaded.settled}
            parts += [f"--decide {k}={v}" for k, v in sorted(chosen.items())]
    elif draft.systems and not draft.template:
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


def _quote(text: str) -> str:
    return f'"{text}"' if any(c in text for c in " '\"$") else text


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
    imported: bool | None = Field(default=None, description="Start from the import")


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
        draft.template, draft.systems, draft.imported = fields.template, None, False
    if fields.systems is not None:
        names = [n.strip() for n in fields.systems if n.strip()]
        if not names:
            raise MirrorError("Name at least one system.", "", "Such as: gitea, mattermost")
        draft.systems, draft.template, draft.imported = names, None, False
    if fields.imported:
        if imports.peek_import(Project(root=root)) is None:
            raise MirrorError(
                "Nothing has been imported into this world yet.",
                "",
                "Choose the files to read first.",
            )
        imports.ready(Project(root=root))
        draft.imported, draft.template, draft.systems = True, None, None
    if fields.seed is not None and fields.seed != draft.seed:
        draft.seed, draft.attempt, draft.company = fields.seed, 0, None
    if fields.another_company:
        if draft.imported:
            imports.keep_company(Project(root=root))
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
        chosen = CompanySuggestion(
            name=name, domain=domain, industry=(fields.industry or base.industry).strip()
        )
        if draft.imported and (chosen.name, chosen.domain) != (base.name, base.domain):
            imports.keep_company(Project(root=root))  # the admin's company, not the import's
        draft.company = chosen
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


# -- importing a description (decision 0025) --------------------------------------------------


def import_project(current: Project, folder: str | None, *, prepare: bool = True) -> Project:
    """The world an import belongs to: the current one, or a folder the wizard is defining.
    When preparing to read files, a new world's draft is given a company first, so the
    import can compare its domain."""
    if not folder:
        return current
    root = resolve_folder(current, folder)
    if not prepare or ((root / MANIFEST).is_file() and not worlddef.draft_path(root).is_file()):
        return Project(root=root)  # a defined world beside this one
    draft = worlddef.load_draft(root)
    if draft.company is None:
        draft.company = suggest_company(draft.seed, attempt=draft.attempt)
        worlddef.save_draft(root, draft)
    return Project(root=root)


def read_import(
    current: Project, folder: str | None, paths: list[Path], as_: str | None = None
) -> imports.ImportReview:
    return imports.import_sources(import_project(current, folder), paths, as_)


def apply_import(project: Project) -> list[Change]:
    """Apply the reviewed import. In a world the wizard is defining, the world then starts
    from it: its systems replace the template's, and every later answer keeps them."""
    root = project.root.resolve()
    if not worlddef.draft_path(root).is_file():
        return imports.apply_import(project)
    imports.ready(project)
    draft = worlddef.load_draft(root)
    draft.imported, draft.template, draft.systems = True, None, None
    draft.company = draft.company or suggest_company(draft.seed, attempt=draft.attempt)
    draft.step = max(draft.step, 2)  # the wizard continues with the company
    return worlddef.save_draft(root, draft)


def new_from_import(
    directory: Path,
    paths: list[Path],
    *,
    as_: str | None = None,
    decisions: dict[str, str] | None = None,
    company: CompanySuggestion | None = None,
    seed: int | None = None,
    people: int = 25,
    history: int = 180,
    tidiness: worlddef.Tidiness = "realistic",
    data: dict[str, int] | None = None,
    links: dict[str, bool] | None = None,
) -> Path:
    """`mirror world new --import`: the wizard's import start in one command. If a
    disagreement is left to settle, the draft is kept and the error says how to finish."""
    root = directory.resolve()
    draft = worlddef.load_draft(root)
    if seed is not None and seed != draft.seed:
        draft.seed, draft.attempt, draft.company = seed, 0, None
    draft.imported, draft.template, draft.systems = True, None, None
    draft.company = company or draft.company or suggest_company(draft.seed, attempt=draft.attempt)
    draft.people, draft.history, draft.tidiness = people, history, tidiness
    draft.data = {**worlddef.DATA_DEFAULTS, **(data or {})}
    draft.links = {**worlddef.LINK_DEFAULTS, **(links or {})}
    worlddef.save_draft(root, draft)
    project = Project(root=root)
    if paths:
        imports.import_sources(project, paths, as_)
    if company is not None:
        imports.keep_company(project)  # named on the command line: the admin's company
    return finish_from_import(root, decisions)


def finish_from_import(directory: Path, decisions: dict[str, str] | None = None) -> Path:
    """Write the definition of a world started from an import, once it can be applied,
    with any decisions given first."""
    root = directory.resolve()
    for subject, decision in (decisions or {}).items():
        imports.decide(Project(root=root), subject, decision)
    try:
        return worlddef.finish_draft(root, worlddef.load_draft(root))
    except MirrorError as exc:
        raise MirrorError(
            exc.what,
            exc.why,
            f"Settle it with --decide <subject>=<value>, or with "
            f"mirror --project {root} world import decide; then finish: "
            f"mirror world new {root}",
        ) from exc


def defining(project: Project) -> bool:
    """Whether the wizard is still defining this world."""
    return worlddef.draft_path(project.root).is_file()
