# SPDX-License-Identifier: Apache-2.0
"""World definition: start a definition from a template or named systems, show it, clone it,
and report its state (build spec, "World definition and creation")."""

from __future__ import annotations

import hashlib
import json
import secrets
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast

from pydantic import BaseModel, Field
from ruamel.yaml import YAML

from mirrordimensions.catalog.index import Match, match_systems
from mirrordimensions.config.loader import load_model
from mirrordimensions.config.manifest import Manifest
from mirrordimensions.errors import MirrorError
from mirrordimensions.hostos.files import make_dir, write_text
from mirrordimensions.network.ca import create_root_ca
from mirrordimensions.project import MANIFEST, STATE_DIR, Project
from mirrordimensions.service.project import PROJECT_GITIGNORE, render_manifest
from mirrordimensions.world.names import CompanySuggestion, slug, suggest_company

if TYPE_CHECKING:
    from mirrordimensions.service.changes import Change

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
    "collaboration": "workspace",
    "observability": "monitor",
    "itsm": "servicedesk",
    "erp": "erp",
    "analytics": "analytics",
    "security": "security",
    "marketing": "marketing",
    "operations": "ops",
    "developer-tool": "dev",
    "cloud": "cloud",
    "legal": "legal",
    "automation": "automation",
    "devices": "devices",
}
# The ids the template gives these kinds, which agent files grant by (`grants: {code: ...}`)
# and refer to (`${code.url}`): the same whichever way the world was defined.
APP_ID = {"code-hosting": "code", "team-chat": "chat"}
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


def definition_hash(manifest: Manifest, seed: str = "") -> dict[str, str]:
    """Hashes of the parts of a definition, so a change re-runs only the stages it affects.
    `seed` is the digest of what the world uses from its seed folder (decision 0030)."""

    def h(value: Any) -> str:
        return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()[
            :12
        ]

    # Visibility between granted, denied and present takes effect at the next run, like
    # rules; only which systems are absent changes what is built (decision 0021).
    # Exposure to remote agents (decision 0024) changes the sandbox, not what is built.
    # The field is set to None rather than left out, so a world built before it existed
    # hashes the same.
    systems = [
        {**a.model_dump(exclude={"rules", "visibility"}), "remote": None} for a in manifest.apps
    ]
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
        # Sites and devices configure the device platforms (decision 0026).
        "devices": _devices_hash(manifest),
        # What the world uses from its seed folder: the company is generated again.
        "seed": seed,
    }


def project_hash(project: Project, manifest: Manifest) -> dict[str, str]:
    """`definition_hash` for a project: its manifest and what it uses from a seed folder."""
    from mirrordimensions.service import seed as seed_svc

    content = seed_svc.load_content(project)
    return definition_hash(manifest, content.digest if content else "")


NO_DEVICES = hashlib.sha256(b'{"devices": [], "sites": []}').hexdigest()[:12]


def _devices_hash(manifest: Manifest) -> str:
    value = {
        "devices": [d.model_dump() for d in manifest.devices],
        "sites": [s.model_dump() for s in manifest.sites],
    }
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()[:12]


def first_stage_affected(old: dict[str, str], new: dict[str, str]) -> int:
    """1-based stage to resume from: company -> 1, systems -> 2, data -> 4, rules -> none (9)."""
    if old.get("company") != new["company"] or old.get("seed", "") != new.get("seed", ""):
        return 1
    if "absent" in old:
        if old.get("systems") != new["systems"]:
            return 2
        was_absent = set(filter(None, str(old["absent"]).split(",")))
        if was_absent - set(filter(None, new.get("absent", "").split(","))):
            return 2  # a system the world was built without is wanted now
    elif old.get("systems") not in (new["systems"], new.get("systems_v1")):
        return 2  # recorded before "absent" was kept: visibility was in the systems hash
    if old.get("devices", NO_DEVICES) != new.get("devices", NO_DEVICES):
        return 2  # a world built before devices existed had none
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


Tidiness = Literal["tidy", "realistic", "messy"]
DATA_DEFAULTS = {"repositories": 6, "issues": 150, "messages": 2000, "canaries": 3}
LINK_DEFAULTS = {"announce": True, "incidents": True}
WIZARD_STEPS = ("start", "company", "systems", "links", "review", "create")


class Draft(BaseModel):
    """Answers so far to the world wizard (`mirror world new` or the portal), kept so an
    interrupted session resumes. Each saved answer also rewrites mirror.yaml with
    `status: draft`, so the definition can be read, and validates, at every step."""

    seed: int
    attempt: int = 0
    company: CompanySuggestion | None = None
    template: str | None = None
    systems: list[str] | None = None
    people: int | None = None
    history: int | None = None
    tidiness: Tidiness = "realistic"
    links: dict[str, bool] = Field(default_factory=lambda: dict(LINK_DEFAULTS))
    data: dict[str, int] = Field(default_factory=lambda: dict(DATA_DEFAULTS))
    substitute: bool = Field(
        default=True,
        description="Run the system with a twin of the same kind in place of one without",
    )
    step: int = 1  # the portal wizard's step reached, 1-6
    imported: bool = Field(
        default=False,
        description="The systems come from the import in this folder (decision 0025)",
    )


QUESTIONS = ("company", "shape", "people", "history")


def draft_path(root: Path) -> Path:
    return root.resolve() / STATE_DIR / "draft.json"


def load_draft(root: Path) -> Draft:
    path = draft_path(root)
    if path.is_file():
        return Draft.model_validate_json(path.read_text(encoding="utf-8"))
    return Draft(seed=secrets.randbelow(900_000) + 100_000)


def save_draft(root: Path, draft: Draft) -> list[Change]:
    """Keep the answers, and write mirror.yaml as it stands (`status: draft`) once there is
    a company to write it for. A draft started from an import has it applied again, so the
    file always holds both; the changes the import made are returned."""
    root = root.resolve()
    existing = root / MANIFEST
    if existing.is_file() and not _is_draft(existing):
        raise MirrorError(
            f"{root} already holds a world.", f"{MANIFEST} exists there.", "Choose another folder."
        )
    make_dir(draft_path(root).parent, owner_only=True)
    write_text(draft_path(root), draft.model_dump_json(indent=2) + "\n", owner_only=True)
    if draft.company is not None:
        write_text(existing, render_world(root, draft, status="draft"))
        return _with_import(root, draft)
    return []


def _is_draft(path: Path) -> bool:
    return any(line.strip() == "status: draft" for line in path.read_text("utf-8").splitlines())


def next_question(draft: Draft) -> str | None:
    """The first question not yet answered, or None when the draft is complete."""
    if draft.company is None:
        return "company"
    if draft.template is None and not draft.systems and not draft.imported:
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
    made = _write_world(root, draft)
    draft_path(root).unlink(missing_ok=True)
    return made


def render_world(root: Path, draft: Draft, status: Literal["draft", "defined"]) -> str:
    """The mirror.yaml a draft describes. The command line and the portal both write this,
    so the same answers give the same file."""
    company = draft.company or suggest_company(draft.seed, attempt=draft.attempt)
    text = render_manifest(slug(root.name) or slug(company.name), company, draft.seed)
    text = text.replace("  size: 25\n", f"  size: {draft.people or 25}\n")
    text = text.replace("  history_days: 180\n", f"  history_days: {draft.history or 180}\n")
    text = text.replace("  tidiness: realistic\n", f"  tidiness: {draft.tidiness}\n")
    if status == "draft":
        text = text.replace("\nname: ", "\nstatus: draft\nname: ", 1)
    data = {**DATA_DEFAULTS, **draft.data}
    for key, default in DATA_DEFAULTS.items():
        text = text.replace(f"  {key}: {default}\n", f"  {key}: {int(data[key])}\n")
    links = {**LINK_DEFAULTS, **draft.links}
    if not links["announce"]:
        text = text.replace("  - announce: {from: code, to: chat, channel: engineering}\n", "")
    if not links["incidents"]:
        text = text.replace("  - incidents: {in: [chat, code]}\n", "")
    if not any(links.values()):
        text = text.replace("links:\n", "links: []\n")
    template = draft.template if draft.template or draft.systems else "software-team"
    if draft.imported:
        # The import brings the systems; links are added once it is known which exist.
        head = text[: text.index("apps:\n")]
        text = head + "apps: []\nlinks: []\n" + _after_links(text)
    elif draft.systems and not draft.template:
        matches = match_systems(draft.systems)
        built = app_entries(matches, company.domain, draft.substitute)
        if not built.running:
            asked = ", ".join(m.entry.name if m.entry else m.query for m in matches)
            raise MirrorError(
                "None of these systems can be built yet.",
                f"Asked for: {asked}. The systems the mirror runs today are "
                f"{', '.join(buildable_names())}.",
                "Name one of those (--systems gitea,mattermost), or start from the template: "
                "mirror world new --template software-team",
            )
        apps = built.lines
        start = text.index("apps:\n") + len("apps:\n")
        end = text.index("links:")
        text = text[:start] + "".join(apps) + text[end:]
    elif template not in TEMPLATES:
        raise MirrorError(
            f"Unknown template {template!r}.",
            f"Templates: {', '.join(TEMPLATES)}.",
            "Run: mirror world new --template software-team",
        )
    return text


class AppEntries(BaseModel):
    lines: list[str]
    running: set[str]
    ids: set[str]
    hosts: set[str]


def app_entries(
    matches: list[Match],
    domain: str,
    substitute: bool,
    running: set[str] | None = None,
    ids: set[str] | None = None,
    hosts: set[str] | None = None,
) -> AppEntries:
    """mirror.yaml entries for matched systems, after any a world already has (`running`,
    `ids`, `hosts`): a stand-in of the same kind for a system with no twin, if allowed."""
    running = set(running or ()) | {m.entry.slug for m in matches if m.entry and m.buildable}
    ids = set(ids or ())
    hosts = set(hosts or ())
    lines: list[str] = []
    for i, match in enumerate(matches):
        if match.entry is None:
            lines.append(f"  # {match.query}: not in the catalog; left out\n")
            continue
        e = match.entry
        host = f"{HOSTNAME_PREFIX.get(e.kind, slug(e.name)[:30])}.{domain}"
        if host in hosts:  # a second system of the same kind goes by its own name
            host = f"{slug(e.name)[:30]}.{domain}"
        hosts.add(host)
        product, instead_of = e.slug, ""
        usable = match.buildable
        if not usable and substitute and match.instead and match.instead.slug not in running:
            product, instead_of, usable = match.instead.slug, e.slug, True
            running.add(product)
        app_id = APP_ID.get(e.kind) or slug(e.kind)[:20] or f"app{i}"
        n = 2
        while app_id in ids:  # a second system of the same kind
            app_id, n = f"{(APP_ID.get(e.kind) or slug(e.kind))[:18]}-{n}", n + 1
        ids.add(app_id)
        line = f"  - id: {app_id}\n    kind: {e.kind}\n    product: {product}\n"
        if instead_of:
            line += f"    in_place_of: {instead_of}    # {e.name} has no twin yet; {match.instead.name if match.instead else product} runs here instead\n"
        line += f"    hostname: {host}\n    visibility: granted\n"
        if not usable:
            line += "    build: unavailable    # no twin yet: recorded, not created\n"
        lines.append(line)
    return AppEntries(lines=lines, running=running, ids=ids, hosts=hosts)


def _after_links(text: str) -> str:
    """What follows the links block in a rendered manifest."""
    rest = text[text.index("links:") :].split("\n")[1:]
    i = 0
    while i < len(rest) and (rest[i].startswith(" ") or not rest[i]):
        i += 1
    return "\n".join(rest[i:])


LINK_LINES = {
    "announce": ("  - announce: {from: code, to: chat, channel: engineering}\n", ("code", "chat")),
    "incidents": ("  - incidents: {in: [chat, code]}\n", ("chat", "code")),
}


def _with_import(root: Path, draft: Draft) -> list[Change]:
    """Apply the folder's import to a draft started from it: its systems, the company it
    proposes, and the links its systems allow. Returns what the import changed."""
    from mirrordimensions.service import imports

    project = Project(root=root)
    if not draft.imported or imports.peek_import(project) is None:
        return []
    changes = imports.apply_import(project)
    text = project.manifest_path.read_text(encoding="utf-8")
    data: dict[str, Any] = YAML(typ="safe").load(text) or {}  # pyright: ignore[reportUnknownMemberType]
    apps = cast(list[dict[str, Any]], data.get("apps") or [])
    ids = {str(a.get("id")) for a in apps}
    wanted = {**LINK_DEFAULTS, **draft.links}
    lines = [line for key, (line, needs) in LINK_LINES.items() if wanted[key] and set(needs) <= ids]
    if lines and "\nlinks: []\n" in text:
        text = text.replace("\nlinks: []\n", "\nlinks:\n" + "".join(lines), 1)
        write_text(project.manifest_path, text)
    company = cast(dict[str, Any], data.get("company") or {})
    if draft.company is not None and (
        company.get("name") != draft.company.name or company.get("domain") != draft.company.domain
    ):
        draft.company = CompanySuggestion(
            name=str(company["name"]),
            domain=str(company["domain"]),
            industry=draft.company.industry,
        )
        write_text(draft_path(root), draft.model_dump_json(indent=2) + "\n", owner_only=True)
    return changes


def _write_world(root: Path, draft: Draft) -> Path:
    root = root.resolve()
    existing = root / MANIFEST
    if existing.exists() and not _is_draft(existing):
        raise MirrorError(
            f"{root} already holds a world.", f"{MANIFEST} exists there.", "Choose another folder."
        )
    if draft.imported:
        from mirrordimensions.service import imports

        imports.ready(Project(root=root))  # refuses, saying what is left to settle
    text = render_world(root, draft, status="defined")
    company = draft.company or suggest_company(draft.seed, attempt=draft.attempt)
    make_dir(root)
    write_text(existing, text)
    _with_import(root, draft)
    write_text(root / ".gitignore", PROJECT_GITIGNORE)
    make_dir(root / "agents")
    make_dir(root / STATE_DIR, owner_only=True)
    if not (root / STATE_DIR / "ca" / "root-ca.crt").is_file():
        create_root_ca(root / STATE_DIR / "ca", company.name, draft.seed)
    load = load_model(existing, Manifest)
    if load[0] is None:
        raise MirrorError(
            "The new definition is not valid.", load[1][0].render(), "Report this as a bug."
        )
    return root


def new_world(
    path: Path,
    template: str | None = None,
    systems: list[str] | None = None,
    people: int = 25,
    history: int = 180,
    seed: int | None = None,
    industry: str | None = None,
    company: CompanySuggestion | None = None,
    tidiness: Tidiness = "realistic",
    data: dict[str, int] | None = None,
    links: dict[str, bool] | None = None,
    substitute: bool = True,
) -> Path:
    """Write a definition in one go: a template, or named systems matched against the catalog."""
    seed = seed if seed is not None else secrets.randbelow(900_000) + 100_000
    draft = Draft(
        seed=seed,
        company=company or suggest_company(seed, industry),
        template=template if template or systems else "software-team",
        systems=systems,
        people=people,
        history=history,
        tidiness=tidiness,
        data={**DATA_DEFAULTS, **(data or {})},
        links={**LINK_DEFAULTS, **(links or {})},
        substitute=substitute,
    )
    return _write_world(path, draft)


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
        and first_stage_affected(record.get("hashes", {}), project_hash(project, manifest)) <= 8
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
    record = {"last_stage": stage, "hashes": project_hash(project, manifest), "failed": failed}
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


def buildable_names() -> list[str]:
    from mirrordimensions.catalog.index import load

    return sorted(e.name for e in load() if e.twin_status in ("buildable", "verified"))


def system_notes(manifest: Manifest) -> list[str]:
    """What a person should know about the systems they asked for: what runs in place of a
    product with no twin, and what is left out."""
    from mirrordimensions.catalog.index import resolve

    notes: list[str] = []
    for a in manifest.apps:
        if a.in_place_of:
            theirs = resolve(a.in_place_of)
            ours = resolve(a.product or "")
            t, o = (theirs.name if theirs else a.in_place_of), (ours.name if ours else a.product)
            notes.append(
                f"{t} has no twin yet, so {o} runs in its place at {a.hostname}. An agent "
                f"written for {t}'s API must use {o}'s API or the world's MCP server; "
                "see docs/your-company.md."
            )
        elif a.build == "unavailable":
            entry = resolve(a.product or "")
            name = entry.name if entry else a.id
            same = next(
                (b for b in manifest.apps if b is not a and b.kind == a.kind and b.build is None),
                None,
            )
            if same is not None:
                notes.append(
                    f"{name} has no twin yet; {same.product} at {same.hostname} is this world's "
                    f"{a.kind}, so {name} is recorded in mirror.yaml but not created."
                )
                continue
            notes.append(
                f"{name} has no twin yet and nothing of its kind runs in its place, so the "
                "world leaves it out. It is recorded in mirror.yaml for when one arrives."
            )
    return notes


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
            + (f" (in place of {a.in_place_of})" if a.in_place_of else "")
            + (" (unavailable: no twin yet)" if a.build == "unavailable" else "")
            for a in manifest.apps
        ],
        "notes": system_notes(manifest),
        "links": [f"{k}: {v}" for link in manifest.links for k, v in link.items()],
        "data": manifest.data.model_dump(exclude_none=True) if manifest.data else {},
    }


# The systems the software-team template runs, for adding to it.
TEMPLATE_SYSTEMS = {"software-team": ["gitea", "mattermost"]}


class Proposal(BaseModel):
    """The systems an industry's profile proposes, each with what the world would run."""

    profile: str
    industry: str
    systems: list[str]
    lines: list[str]


def propose(industry: str | None, substitute: bool = True) -> Proposal | None:
    """What a company in this industry usually runs (decision 0028, point 3), or None when
    the industry matches no profile or the profile names no systems."""
    from mirrordimensions.world import profile as profiles

    if not industry:
        return None
    found = profiles.match(industry)
    if found is None or not found.systems.typical:
        return None
    lines: list[str] = []
    running: set[str] = set()
    for m in match_systems(found.systems.typical):
        if m.entry is None:
            continue
        if m.buildable:
            lines.append(f"{m.entry.name}: runs as itself")
            running.add(m.entry.slug)
        elif substitute and m.instead and m.instead.slug not in running:
            lines.append(f"{m.entry.name}: {m.instead.name} runs in its place")
            running.add(m.instead.slug)
        else:
            lines.append(f"{m.entry.name}: no twin yet, recorded and left out")
    return Proposal(
        profile=found.name, industry=industry, systems=list(found.systems.typical), lines=lines
    )


def add_systems(project: Project, systems: list[str], substitute: bool = True) -> list[str]:
    """Add systems to a defined world's mirror.yaml, in place, keeping everything else in the
    file as it is. Returns the systems added, as they will run."""
    manifest, problems = load_model(project.manifest_path, Manifest)
    if manifest is None:
        raise MirrorError(
            "mirror.yaml is not valid, so nothing was added.",
            "; ".join(p.message for p in problems[:3]),
            "Fix it first: mirror validate",
        )
    have = {a.product for a in manifest.apps} | {
        a.in_place_of for a in manifest.apps if a.in_place_of
    }
    matches = [m for m in match_systems(systems) if not (m.entry and m.entry.slug in have)]
    if not matches:
        raise MirrorError(
            "The world already has those systems.",
            f"Asked for: {', '.join(systems)}.",
            "See what it has: mirror world show",
        )
    built = app_entries(
        matches,
        manifest.company.domain,
        substitute,
        running={a.product for a in manifest.apps if a.product and a.build != "unavailable"},
        ids={a.id for a in manifest.apps},
        hosts={a.hostname for a in manifest.apps},
    )
    text = project.manifest_path.read_text(encoding="utf-8")
    lines = text.split("\n")
    try:
        at = lines.index("apps:")
    except ValueError:
        raise MirrorError(
            "mirror.yaml has no top-level apps list to add to.",
            "The file was changed by hand in a way this command cannot follow.",
            "Add the system under apps: yourself; mirror schema world shows the format.",
        ) from None
    end = at + 1
    while end < len(lines) and (lines[end].startswith((" ", "#")) or not lines[end].strip()):
        end += 1
    while end > at + 1 and not lines[end - 1].strip():
        end -= 1
    added = "".join(built.lines).rstrip("\n").split("\n")
    updated = "\n".join(lines[:end] + added + lines[end:])
    candidate, problems = _validate_text(updated)
    if candidate is None:
        raise MirrorError(
            "Adding these systems would make mirror.yaml invalid, so nothing was changed.",
            "; ".join(problems[:3]),
            "Add them by hand, or report this.",
        )
    write_text(project.manifest_path, updated)
    return sorted(built.ids - {a.id for a in manifest.apps})


def _validate_text(text: str) -> tuple[Manifest | None, list[str]]:
    loaded: Any = YAML(typ="safe").load(text)  # pyright: ignore[reportUnknownMemberType]
    try:
        return Manifest.model_validate(loaded), []
    except Exception as exc:  # noqa: BLE001  # pydantic's errors, reported to the user
        return None, [str(exc)[:300]]
