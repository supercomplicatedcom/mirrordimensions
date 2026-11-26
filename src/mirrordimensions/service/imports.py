# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""World import: one draft from many files, reviewed, then applied (build spec, "World
import"; decision 0025).

`import_sources` reads each file in place on the host with the importer that recognizes it
and adds its facts to `.mirror/import/draft.json` (owner-only). The review is computed from
the facts each time: facts about the same subject are combined and list every source; facts
that disagree are a conflict the admin settles. `apply` refuses while a conflict is open,
then writes `mirror.yaml` (and, for an MCP server, its tool list and the surfaces its tools
map to) and records which facts each line came from.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import BaseModel, Field

from mirrordimensions.catalog.index import Entry, resolve
from mirrordimensions.errors import MirrorError
from mirrordimensions.hostos.files import make_dir, write_text
from mirrordimensions.importers import Fact, Importer, ImportResult, available
from mirrordimensions.importers._common import load_document
from mirrordimensions.importers.scrub import EMAIL, secret_like
from mirrordimensions.project import Project
from mirrordimensions.service.changes import Change
from mirrordimensions.world.names import slug

Decision = Literal["granted", "denied", "present", "unavailable", "leave-out"]
DECISION_TEXT: dict[str, str] = {
    "granted": "Include, granted",
    "denied": "Include, denied",
    "present": "Present, not disclosed",
    "unavailable": "Recorded, not built (no twin yet)",
    "leave-out": "Leave out",
    "use-domain": "Use this name and domain",
    "keep": "Keep the world's company",
}
# Precedence for what the agent can call, when a first proposal needs a default.
PRECEDENCE = ("mcp-config", "mcp-tools", "openapi", "identity", "catalog", "terraform")
KIND_IDS = {"code-hosting": "code", "team-chat": "chat"}  # the ids the templates use
GAPS = (
    ("Business rules", "Approval chains and validation are in no file. Product defaults are used."),
    (
        "How much each system holds",
        "Set in mirror.yaml under data, or on the wizard's Links and data step.",
    ),
    ("The people", "Always invented. No names, emails or user ids are read from any file."),
)


class SourceRead(BaseModel):
    importer: str
    label: str
    file: str
    path: str = Field(default="", description="Where it was read, on this machine")
    summary: str
    skipped_secrets: int = 0
    skipped_people: int = 0
    skipped: dict[str, int] = Field(default_factory=dict[str, int])


class ImportDraft(BaseModel):
    """What is kept on disk: the facts and the admin's decisions. Everything else is derived."""

    version: Literal[1] = 1
    sources: list[SourceRead] = Field(default_factory=list[SourceRead])
    facts: list[Fact] = Field(default_factory=list[Fact])
    decisions: dict[str, str] = Field(default_factory=dict[str, str])
    settled: dict[str, str] = Field(default_factory=dict[str, str])
    applied: dict[str, list[str]] = Field(
        default_factory=dict[str, list[str]],
        description="Each entry written to mirror.yaml, and the facts it came from",
    )


class Choice(BaseModel):
    value: str
    sources: list[str]


class Conflict(BaseModel):
    id: str  # "<subject>.<field>"
    subject: str
    label: str
    field: str
    choices: list[Choice]
    settled: str | None = None


class ToolMapping(BaseModel):
    name: str
    mapped: bool
    backed_by: str | None = None  # the system's subject
    reason: str = ""


class Finding(BaseModel):
    id: str  # the subject
    label: str
    kind: str  # system, mcp-server, internal-service, database, queue, bucket, cache, dns
    kind_label: str
    product: str | None = None
    twin: str | None = None  # the product a twin runs, when one can be built
    hostname: str | None = None
    endpoint: str | None = None
    sources: list[str]
    understood: str
    options: list[str]
    decision: str
    proposed: bool  # the decision is the default, not the admin's
    facts: list[str]
    tools: list[ToolMapping] = Field(default_factory=list[ToolMapping])
    endpoints: int = 0


class ImportReview(BaseModel):
    sources: list[SourceRead]
    findings: list[Finding]
    conflicts: list[Conflict]
    gaps: list[dict[str, str]]
    found: int
    buildable: int
    open_conflicts: int
    skipped_secrets: int
    skipped_people: int
    words: dict[str, str] = Field(
        default_factory=lambda: dict(DECISION_TEXT), description="Each decision, in words"
    )


class ImportKind(BaseModel):
    name: str
    label: str


def kinds() -> list[ImportKind]:
    """The kinds of file import reads: the built-in importers and any plug-in."""
    return [ImportKind(name=i.name, label=i.label) for i in available()]


# -- the draft on disk ------------------------------------------------------------------------


def _dir(project: Project) -> Path:
    return project.state_dir / "import"


def _path(project: Project) -> Path:
    return _dir(project) / "draft.json"


def _load(project: Project) -> ImportDraft | None:
    path = _path(project)
    if not path.is_file():
        return None
    return ImportDraft.model_validate_json(path.read_text(encoding="utf-8"))


def _save(project: Project, draft: ImportDraft) -> None:
    make_dir(_dir(project), owner_only=True)
    write_text(_path(project), draft.model_dump_json(indent=2) + "\n", owner_only=True)


def _require(project: Project) -> ImportDraft:
    draft = _load(project)
    if draft is None:
        raise MirrorError(
            "Nothing has been imported.",
            "",
            "Run: mirror world import <file>...",
        )
    return draft


# -- reading files ----------------------------------------------------------------------------


def detect_source(path: Path, as_: str | None = None) -> Importer:
    """The importer for a file: the one named by `as_`, or the one that recognizes it."""
    importers = available()
    if as_ is not None:
        found = next((i for i in importers if i.name == as_), None)
        if found is None:
            raise MirrorError(
                f"No importer called {as_!r}.",
                f"Importers: {', '.join(i.name for i in importers)}.",
                "Pass one of them with --as, or leave --as out to detect it.",
            )
        return found
    data = _read(path)
    for importer in importers:
        if importer.detect(path, data):
            return importer
    raise MirrorError(
        f"{path.name} is not a kind of file import reads.",
        "Import reads MCP client configuration and exported tool lists, OpenAPI 3 "
        "specifications, and Terraform state from `terraform show -json`.",
        "Pass the kind with --as if it was not recognized: " + ", ".join(i.name for i in importers),
    )


def _read(path: Path) -> Any:
    if not path.is_file():
        raise MirrorError(f"{path} does not exist.", "", "Check the path.")
    try:
        return load_document(path)
    except (OSError, UnicodeDecodeError) as exc:
        raise MirrorError(f"{path.name} could not be read.", str(exc), "Check the file.") from exc


def import_sources(project: Project, paths: Iterable[Path], as_: str | None = None) -> ImportReview:
    """Read each file in place and add its facts to the draft. A file read again replaces
    what it contributed before."""
    draft = _load(project) or ImportDraft()
    for path in paths:
        path = Path(path).expanduser()
        importer = detect_source(path, as_)
        result = importer.read(path, _read(path))
        result = _guard(result)
        draft.facts = [
            f
            for f in draft.facts
            if (f.source.importer, f.source.file) != (importer.name, path.name)
        ]
        draft.sources = [
            s for s in draft.sources if (s.importer, s.file) != (importer.name, path.name)
        ]
        draft.facts += result.facts
        draft.sources.append(
            SourceRead(
                importer=importer.name,
                label=importer.label,
                file=path.name,
                path=str(path.resolve()),
                summary=result.summary,
                skipped_secrets=result.skipped_secrets,
                skipped_people=result.skipped_people,
                skipped=result.skipped,
            )
        )
    _save(project, draft)
    return review(project, draft)


def _guard(result: ImportResult) -> ImportResult:
    """The last check before a fact exists: whatever an importer kept, no string in it may
    look like a credential or hold an email address. A credential's string is emptied; a
    sentence with an address in it is removed, with the name that usually goes with it.
    Each is counted."""

    def clean(value: Any) -> Any:
        if isinstance(value, str):
            if EMAIL.search(value):
                # A contact's name sits beside their address: the whole sentence goes.
                result.skipped_people += 1
                kept = [p for p in re.split(r"(?<=[.!?])\s+", value) if not EMAIL.search(p)]
                return " ".join(kept)
            if secret_like(value):
                result.skipped_secrets += 1
                return ""
            return value
        if isinstance(value, dict):
            return {k: clean(v) for k, v in cast(dict[str, Any], value).items()}
        if isinstance(value, list):
            return [clean(v) for v in cast(list[Any], value)]
        return value

    for f in result.facts:
        f.value = clean(f.value)
    return result


def get_import(project: Project) -> ImportReview:
    return review(project, _require(project))


def load_draft(project: Project) -> ImportDraft | None:
    """The draft as kept on disk: sources, facts and decisions."""
    return _load(project)


def peek_import(project: Project) -> ImportReview | None:
    """The review, or None when nothing has been imported."""
    draft = _load(project)
    return None if draft is None else review(project, draft)


def keep_company(project: Project) -> None:
    """The admin set the company by hand: the import no longer proposes its own."""
    draft = _load(project)
    if draft is not None and draft.decisions.get(COMPANY) != "keep":
        draft.decisions[COMPANY] = "keep"
        _save(project, draft)


def discard_import(project: Project) -> None:
    import shutil

    if not _dir(project).exists():
        raise MirrorError("Nothing has been imported.", "", "Run: mirror world import <file>...")
    shutil.rmtree(_dir(project))


# -- the review -------------------------------------------------------------------------------


def _source_label(f: Fact, labels: dict[str, str]) -> str:
    return f"{labels.get(f.source.importer, f.source.importer)} ({f.source.file})"


def _rank(f: Fact) -> int:
    return (
        PRECEDENCE.index(f.source.importer) if f.source.importer in PRECEDENCE else len(PRECEDENCE)
    )


def review(project: Project, draft: ImportDraft) -> ImportReview:
    labels = {s.importer: s.label for s in draft.sources}
    by_subject: dict[str, list[Fact]] = {}
    for f in draft.facts:
        by_subject.setdefault(f.subject, []).append(f)
    conflicts: list[Conflict] = []
    findings: list[Finding] = []
    systems = {s: fs for s, fs in by_subject.items() if not s.startswith(_RESOURCE_PREFIXES)}
    dns = {
        f.value["hostname"]: f for s, fs in by_subject.items() if s.startswith("dns:") for f in fs
    }
    claimed: set[str] = set()
    for subject, facts in sorted(systems.items()):
        if not any(f.kind == "system" for f in facts):
            continue
        finding, conflict = _system_finding(subject, facts, draft, labels, dns)
        # A DNS record for a system's hostname is evidence for it, not a finding of its own.
        named = {c.value for c in (conflict.choices if conflict else [])} | {finding.hostname or ""}
        claimed |= {h for h in dns if h in named}
        findings.append(finding)
        if conflict is not None:
            conflicts.append(conflict)
    included = {f.id: f for f in findings if f.decision in ("granted", "denied", "present")}
    for finding in findings:
        if finding.kind == "mcp-server":
            _map_tools(finding, by_subject[finding.id], included, draft)
    for subject, facts in sorted(by_subject.items()):
        if not subject.startswith(_RESOURCE_PREFIXES):
            continue
        if subject.startswith("dns:") and facts[0].value["hostname"] in claimed:
            continue
        findings.append(_resource_finding(subject, facts, draft, labels))
    company = _company_finding(project, findings, draft)
    if company is not None:
        findings.insert(0, company)
    for c in conflicts:
        c.settled = draft.settled.get(c.id)
    return ImportReview(
        sources=draft.sources,
        findings=findings,
        conflicts=conflicts,
        gaps=[{"what": w, "why": y} for w, y in GAPS],
        found=len(findings),
        buildable=sum(1 for f in findings if f.twin and f.decision != "leave-out"),
        open_conflicts=sum(1 for c in conflicts if c.settled is None),
        skipped_secrets=sum(s.skipped_secrets for s in draft.sources),
        skipped_people=sum(s.skipped_people for s in draft.sources),
    )


_RESOURCE_PREFIXES = ("database:", "queue:", "bucket:", "cache:", "dns:")
_RESOURCE_LABELS = {
    "database": "Database",
    "queue": "Queue",
    "bucket": "Storage bucket",
    "cache": "Cache",
    "dns": "DNS record",
}


def _system_finding(
    subject: str,
    facts: list[Fact],
    draft: ImportDraft,
    labels: dict[str, str],
    dns: dict[str, Fact],
) -> tuple[Finding, Conflict | None]:
    systems = sorted((f for f in facts if f.kind == "system"), key=_rank)
    merged: dict[str, Any] = {}
    for f in reversed(systems):  # the most authoritative source last, so it wins
        merged.update(f.value)
    mcp = subject.startswith("mcp:") or merged.get("kind") == "mcp-server"
    entry: Entry | None = None if mcp else resolve(str(merged.get("product") or ""))
    twin = entry.twin if entry and entry.twin_status in ("buildable", "verified") else None
    kind = (
        "mcp-server"
        if mcp
        else ("system" if entry else str(merged.get("kind") or "internal-service"))
    )
    name = str(merged.get("name") or subject.removeprefix("mcp:"))
    # Hostnames: the same from every source, or a conflict to settle.
    hosts: dict[str, list[Fact]] = {}
    for f in facts:
        if f.kind == "hostname":
            hosts.setdefault(str(f.value["hostname"]), []).append(f)
    conflict: Conflict | None = None
    hostname: str | None = None
    if len(hosts) > 1:
        conflict = Conflict(
            id=f"{subject}.hostname",
            subject=subject,
            label=name,
            field="hostname",
            choices=[
                Choice(
                    value=h,
                    sources=sorted({_source_label(f, labels) for f in fs + _dns_for(dns, h)}),
                )
                for h, fs in sorted(hosts.items(), key=lambda kv: min(_rank(f) for f in kv[1]))
            ],
        )
        hostname = draft.settled.get(conflict.id)
    elif hosts:
        hostname = next(iter(hosts))
    endpoint = next(
        (
            str(f.value["endpoint"])
            for f in facts
            if f.kind == "hostname" and f.value.get("endpoint")
        ),
        None,
    )
    evidence = list(facts) + ([dns[hostname]] if hostname in dns else [])
    sources = sorted({_source_label(f, labels) for f in evidence})
    callable_ = any(f.source.importer in ("mcp-config", "mcp-tools", "openapi") for f in facts)
    if mcp:
        options = ["granted", "unavailable", "leave-out"]
        default = "granted"
    elif twin:
        options = ["granted", "denied", "present", "leave-out"]
        default = "granted" if callable_ else "denied"
    else:
        options = ["unavailable", "leave-out"]
        default = "unavailable"
    endpoints = sum(1 for f in facts if f.kind == "endpoint")
    if mcp:
        understood = f"A tool server the agent connects to{f' at {hostname}' if hostname else ''}"
    elif twin:
        understood = f"Matched to {entry.name if entry else twin}, which can be built"
    elif entry:
        understood = f"{entry.name}: no twin in this release"
    else:
        understood = "An internal service: no twin can stand in for it"
    if endpoints:
        understood += f"; {endpoints} endpoint(s) read from its specification"
    if hostname is None and not conflict:
        understood += "; no file gave its hostname"
    decision = draft.decisions.get(subject)
    finding = Finding(
        id=subject,
        label=entry.name if entry else name,
        kind=kind,
        kind_label="MCP server"
        if mcp
        else (_kind_label(entry.kind) if entry else "Internal service"),
        product=entry.slug if entry else None,
        twin=twin,
        hostname=hostname,
        endpoint=endpoint,
        sources=sources,
        understood=understood,
        options=options,
        decision=decision if decision in options else default,
        proposed=decision not in options,
        facts=[f.id for f in evidence],
        endpoints=endpoints,
    )
    return finding, conflict


COMPANY = "company"


def _registrable(host: str) -> str:
    return ".".join(host.split(".")[-2:])


def _company_finding(
    project: Project, findings: list[Finding], draft: ImportDraft
) -> Finding | None:
    """When the imported hostnames share one domain the world's company does not use, the
    invented people would have addresses elsewhere than the systems they work in. Propose
    the company take that domain, and a name to match."""
    from collections import Counter

    from mirrordimensions.service.agents import _manifest  # pyright: ignore[reportPrivateUsage]

    hosts = [
        f.hostname
        for f in findings
        if f.hostname and f.kind in ("system", "mcp-server", "internal-service")
    ]
    if not hosts:
        return None
    domain, _ = Counter(_registrable(h) for h in hosts).most_common(1)[0]
    current = _manifest(project).company
    if current.domain.lower() == domain:
        return None
    name = " ".join(w.capitalize() for w in domain.split(".")[0].replace("_", "-").split("-"))
    options = ["use-domain", "keep"]
    decision = draft.decisions.get(COMPANY)
    return Finding(
        id=COMPANY,
        label=f"{name} ({domain})",
        kind="company",
        kind_label="Company",
        sources=[f"hostnames of {len(hosts)} system(s)"],
        understood=(
            f"The systems are under {domain}; the world's company is {current.name} "
            f"({current.domain}). Using {domain} gives the invented people addresses where "
            "they work, and the company the matching name. Its people stay invented."
        ),
        options=options,
        decision=decision if decision in options else "use-domain",
        proposed=decision not in options,
        facts=[],
    )


def _dns_for(dns: dict[str, Fact], host: str) -> list[Fact]:
    return [dns[host]] if host in dns else []


def _kind_label(kind: str) -> str:
    return kind.replace("-", " ").capitalize()


def _resource_finding(
    subject: str, facts: list[Fact], draft: ImportDraft, labels: dict[str, str]
) -> Finding:
    value = facts[0].value
    category = str(value["category"])
    label = str(value.get("hostname") or value.get("name") or subject)
    detail = f", {value['engine']}" if value.get("engine") else ""
    options = ["present", "leave-out"]
    decision = draft.decisions.get(subject)
    return Finding(
        id=subject,
        label=label,
        kind=category,
        kind_label=_RESOURCE_LABELS.get(category, category),
        sources=sorted({_source_label(f, labels) for f in facts}),
        understood=(
            f"{value.get('type', category)}{detail}: recorded under infrastructure, not built"
        ),
        options=options,
        decision=decision if decision in options else "present",
        proposed=decision not in options,
        facts=[f.id for f in facts],
    )


# -- tools: what each imported tool calls in a twin ------------------------------------------

_ARG = re.compile(r"\{([A-Za-z_][\w]*)(?:![a-z0-9]+)?\}")  # {name} or {name!b64}: no default


def tool_library(product: str) -> dict[str, Any]:
    """The MCP tools a twin can serve (`twins/<product>/mcp_tools.yaml`), or nothing."""
    import importlib

    from ruamel.yaml import YAML

    from mirrordimensions.twins.base import get_twin

    twin = get_twin(product)
    if twin is None:
        return {}
    package = type(twin).__module__.rsplit(".", 1)[0]
    path = Path(str(importlib.import_module(package).__file__)).parent / "mcp_tools.yaml"
    if not path.is_file():
        return {}
    return cast(dict[str, Any], YAML(typ="safe").load(path.read_text(encoding="utf-8")) or {})  # pyright: ignore[reportUnknownMemberType]


def _required(surface: dict[str, Any]) -> set[str]:
    return set(_ARG.findall(json.dumps(surface.get("steps", []))))


def _map_tools(
    finding: Finding, facts: list[Fact], included: dict[str, Finding], draft: ImportDraft
) -> None:
    tools = [f.value for f in facts if f.kind == "tool"]
    backing = [f for f in included.values() if f.twin and f.kind == "system"]
    libraries = {f.id: tool_library(str(f.twin)) for f in backing}
    for tool in tools:
        name = str(tool["name"])
        props = set(cast(dict[str, Any], tool.get("inputSchema", {})).get("properties", {}) or {})
        found: ToolMapping | None = None
        for system in backing:
            surface = cast(dict[str, Any], libraries[system.id].get("tools", {})).get(name)
            if surface is None:
                continue
            missing = sorted(_required(cast(dict[str, Any], surface)) - props)
            if missing:
                found = ToolMapping(
                    name=name,
                    mapped=False,
                    reason=(
                        f"{system.label} serves {name}, but this tool has no " + ", ".join(missing)
                    ),
                )
                continue
            found = ToolMapping(name=name, mapped=True, backed_by=system.id)
            break
        finding.tools.append(
            found
            or ToolMapping(name=name, mapped=False, reason="no system in this import serves it")
        )
    mapped = sum(1 for t in finding.tools if t.mapped)
    if not tools:
        finding.understood += "; no tool list was imported (export its tools/list)"
    else:
        finding.understood += (
            f"; {mapped} of {len(tools)} tool(s) mapped to systems that can be built"
        )
    server = next(
        (f.value for f in facts if f.kind == "system" and f.value.get("server_info")), None
    )
    if not mapped or server is None:
        if "granted" in finding.options:
            finding.options.remove("granted")
        if finding.decision == "granted":
            finding.decision = "unavailable"
        if server is None and tools:
            finding.understood += "; the export has no serverInfo with a name and version"


# -- deciding ---------------------------------------------------------------------------------


def decide(project: Project, subject: str, decision: str) -> ImportReview:
    """Settle a conflict (`<subject>.hostname` and the value to keep), or change a finding's
    decision (`<subject>` and one of its options)."""
    draft = _require(project)
    current = review(project, draft)
    conflict = next((c for c in current.conflicts if c.id == subject), None)
    if conflict is not None:
        values = [c.value for c in conflict.choices]
        if decision not in values:
            raise MirrorError(
                f"{decision!r} is not one of the values the sources give.",
                f"For {conflict.label}'s {conflict.field}: {', '.join(values)}.",
                f"Run: mirror world import decide {subject} <one of them>",
            )
        draft.settled[subject] = decision
        _save(project, draft)
        return review(project, draft)
    finding = next((f for f in current.findings if f.id == subject), None)
    if finding is None:
        known = [f.id for f in current.findings] + [c.id for c in current.conflicts]
        raise MirrorError(
            f"Nothing in the import is called {subject!r}.",
            f"Findings and conflicts: {', '.join(known)}.",
            "Run: mirror world import show",
        )
    if decision not in finding.options:
        raise MirrorError(
            f"{decision!r} is not a decision for {finding.label}.",
            f"Choose one of: {', '.join(finding.options)}.",
            f"Run: mirror world import decide {subject} <decision>",
        )
    draft.decisions[subject] = decision
    _save(project, draft)
    return review(project, draft)


# -- applying ---------------------------------------------------------------------------------


def ready(project: Project, draft: ImportDraft | None = None) -> ImportReview:
    """The review, if it can be applied: every disagreement settled and every system kept
    has a hostname. Refuses, saying what is left, otherwise."""
    draft = draft or _require(project)
    current = review(project, draft)
    open_ = [c for c in current.conflicts if c.settled is None]
    if open_:
        raise MirrorError(
            f"{len(open_)} disagreement(s) between sources are not settled.",
            "; ".join(
                f"{c.label}'s {c.field}: " + " or ".join(ch.value for ch in c.choices)
                for c in open_
            ),
            f"Settle each: mirror world import decide {open_[0].id} <value>",
        )
    missing = [
        f.label
        for f in current.findings
        if f.kind in ("system", "mcp-server", "internal-service")
        and f.decision != "leave-out"
        and not f.hostname
    ]
    if missing:
        raise MirrorError(
            f"No file gave a hostname for {', '.join(missing)}.",
            "Every system in the world needs the hostname the agent uses for it.",
            "Import a file that names it, or leave it out: "
            "mirror world import decide <subject> leave-out",
        )
    return current


def apply_import(project: Project) -> list[Change]:
    """Write the reviewed import into mirror.yaml. Systems already defined are updated in
    place (matched by product); new ones are added; nothing else is removed."""
    from mirrordimensions.service.systems import edit_manifest

    draft = _require(project)
    current = ready(project, draft)
    changes: list[Change] = []
    applied: dict[str, list[str]] = {}
    tool_files: dict[str, tuple[str, str]] = {}

    def edit(data: Any) -> None:
        company = next((f for f in current.findings if f.id == COMPANY), None)
        if company is not None and company.decision == "use-domain":
            name, _, domain = company.label.rpartition(" (")
            before = {"name": data["company"]["name"], "domain": data["company"]["domain"]}
            data["company"]["name"], data["company"]["domain"] = name, domain.rstrip(")")
            applied["company"] = sorted({i for f in current.findings for i in f.facts})
            changes.append(
                Change(
                    kind="company",
                    target="company",
                    what=f"Company: {company.label}, as its systems' hostnames are",
                    before=before,
                    applies="rebuild",
                )
            )
        if not data.get("apps"):  # a world started from the import has none yet
            data["apps"] = []
        apps = cast(list[dict[str, Any]], data["apps"])
        ids_for: dict[str, str] = {}
        for finding in current.findings:
            if finding.kind == "mcp-server" or finding.decision == "leave-out":
                continue
            if finding.kind in ("system", "internal-service"):
                app_id = _put_system(apps, finding, changes)
                ids_for[finding.id] = app_id
                applied[f"apps.{app_id}"] = finding.facts
        for finding in current.findings:
            if finding.kind != "mcp-server" or finding.decision == "leave-out":
                continue
            app_id, files = _put_mcp(apps, finding, ids_for, draft, changes)
            applied[f"apps.{app_id}"] = finding.facts
            tool_files.update(files)
        infra = cast(list[dict[str, Any]], data.setdefault("infrastructure", []))
        for finding in current.findings:
            if finding.kind not in _RESOURCE_LABELS or finding.decision == "leave-out":
                continue
            name = finding.label
            entry = {"name": name, "kind": finding.kind, "source": "import"}
            fact = next(f for f in draft.facts if f.id == finding.facts[0])
            if fact.value.get("type"):
                entry["type"] = fact.value["type"]
            if fact.value.get("engine"):
                entry["engine"] = fact.value["engine"]
            if not any(i.get("name") == name and i.get("kind") == finding.kind for i in infra):
                infra.append(entry)
                changes.append(
                    Change(
                        kind="system",
                        target=name,
                        what=f"{finding.kind_label} {name}: recorded under infrastructure",
                        applies="rebuild",
                    )
                )
            applied[f"infrastructure.{name}"] = finding.facts

    edit_manifest(project, edit)
    for rel, (text, _) in tool_files.items():  # gathered while mirror.yaml was edited
        make_dir((project.root / rel).parent)
        write_text(project.root / rel, text)
    draft.applied = applied
    _save(project, draft)
    return changes


def _unique_id(apps: list[dict[str, Any]], wanted: str) -> str:
    taken = {str(a.get("id", "")).lower() for a in apps}
    base = (slug(wanted) or "system")[:20].strip("-")
    candidate, n = base, 2
    while candidate.lower() in taken:
        candidate, n = f"{base[:17]}-{n}", n + 1
    return candidate


def _put_system(apps: list[dict[str, Any]], finding: Finding, changes: list[Change]) -> str:
    entry = resolve(finding.product or "") if finding.product else None
    kind = entry.kind if entry else "internal-service"
    product = finding.twin or (entry.slug if entry else None)
    # The same system already in mirror.yaml: by product, then by hostname (an internal
    # service has no product, and applying twice must not add it twice).
    existing = (
        next((a for a in apps if product and a.get("product") == product), None)
        or next(
            (
                a
                for a in apps
                if finding.hostname
                and str(a.get("hostname", "")).lower() == finding.hostname
                and a.get("kind") != "mcp-server"
            ),
            None,
        )
        or next(
            (a for a in apps if finding.twin and a.get("kind") == kind and not a.get("product")),
            None,
        )
    )
    visibility = finding.decision if finding.decision in ("granted", "denied", "present") else None
    if existing is not None:
        before = {k: existing.get(k) for k in ("hostname", "visibility")}
        existing["hostname"] = finding.hostname
        if visibility:
            existing["visibility"] = visibility
        if finding.decision == "unavailable":
            existing["build"] = "unavailable"
        changes.append(
            Change(
                kind="system",
                target=str(existing["id"]),
                what=f"{finding.label}: hostname {finding.hostname}"
                + (f", {visibility}" if visibility else ""),
                before=before,
                applies="rebuild",
            )
        )
        return str(existing["id"])
    app_id = _unique_id(apps, KIND_IDS.get(kind, "") or finding.product or finding.label)
    app: dict[str, Any] = {"id": app_id, "kind": kind}
    if product:
        app["product"] = product
    app["hostname"] = finding.hostname
    app["visibility"] = visibility or "present"
    if finding.decision == "unavailable":
        app["build"] = "unavailable"
    apps.append(app)
    changes.append(
        Change(
            kind="system",
            target=app_id,
            what=f"{finding.label} added at {finding.hostname}"
            + (
                " (recorded, not built: no twin yet)"
                if finding.decision == "unavailable"
                else f", {visibility}"
            ),
            applies="rebuild",
        )
    )
    return app_id


def _put_mcp(
    apps: list[dict[str, Any]],
    finding: Finding,
    ids_for: dict[str, str],
    draft: ImportDraft,
    changes: list[Change],
) -> tuple[str, dict[str, tuple[str, str]]]:
    """An MCP server: its served tool list is the export's, cut to the tools that map; its
    surfaces say what each calls in the systems backing it."""
    from io import StringIO

    from ruamel.yaml import YAML

    name = finding.id.removeprefix("mcp:")
    existing = next(
        (
            a
            for a in apps
            if a.get("kind") == "mcp-server" and a.get("hostname") == finding.hostname
        ),
        None,
    )
    app_id = str(existing["id"]) if existing else _unique_id(apps, name)
    app: dict[str, Any] = existing if existing is not None else {"id": app_id}
    app.update({"kind": "mcp-server", "hostname": finding.hostname, "visibility": "granted"})
    files: dict[str, tuple[str, str]] = {}
    mapped = [t for t in finding.tools if t.mapped and ids_for.get(str(t.backed_by))]
    server = next(
        (
            f.value
            for f in draft.facts
            if f.subject == finding.id and f.kind == "system" and f.value.get("server_info")
        ),
        None,
    )
    if finding.decision == "granted" and mapped and server is not None:
        defs = {
            str(f.value["name"]): f.value
            for f in draft.facts
            if f.subject == finding.id and f.kind == "tool"
        }
        export = {
            "serverInfo": server["server_info"],
            "protocolVersions": server.get("protocol_versions") or ["2025-06-18"],
            "instructions": server.get("instructions", ""),
            "tools": [defs[t.name] for t in mapped],
        }
        backends: dict[str, Any] = {}
        surfaces: dict[str, Any] = {}
        for t in mapped:
            system_id = ids_for[str(t.backed_by)]
            library = tool_library(_twin_of(apps, system_id))
            backends[system_id] = {"auth": library.get("auth", "Bearer")}
            surface = json.loads(json.dumps(library["tools"][t.name]))
            for step in surface.get("steps", []):
                if step.get("app") == "self":
                    step["app"] = system_id
            surfaces[t.name] = surface
        mapping = {"endpoint": finding.endpoint or "/mcp", "backends": backends, "tools": surfaces}
        yaml = YAML()
        yaml.default_flow_style = False
        buffer = StringIO()
        yaml.dump(mapping, buffer)  # pyright: ignore[reportUnknownMemberType]
        tools_rel, surfaces_rel = f"tools/{app_id}.json", f"tools/{app_id}.surfaces.yaml"
        header = (
            "# Written by `mirror world import apply` from the imported tool list\n"
            "# (decision 0025):\n"
            "# what each tool calls in the systems that back it.\n"
        )
        files[tools_rel] = (json.dumps(export, indent=2) + "\n", "tools")
        files[surfaces_rel] = (header + buffer.getvalue(), "surfaces")
        app["serves"] = {
            "tools_from": {"file": tools_rel},
            "surfaces": surfaces_rel,
            "backed_by": sorted(backends),
        }
        app.pop("build", None)
        what = f"MCP server {name} at {finding.hostname}, {len(mapped)} tool(s)"
        unmapped = [t.name for t in finding.tools if not t.mapped]
        if unmapped:
            what += f"; not served (no system backs them): {', '.join(unmapped)}"
    else:
        app["build"] = "unavailable"
        app.pop("serves", None)
        what = (
            f"MCP server {name} at {finding.hostname}: recorded, not built "
            "(no tool maps to a system that can be built)"
        )
    if existing is None:
        apps.append(app)
    changes.append(Change(kind="system", target=app_id, what=what, applies="rebuild"))
    return app_id, files


def _twin_of(apps: list[dict[str, Any]], app_id: str) -> str:
    return str(next(a for a in apps if a.get("id") == app_id).get("product") or "")


def provenance(project: Project) -> dict[str, list[dict[str, Any]]]:
    """For each entry the import wrote to mirror.yaml, the facts it came from."""
    draft = _require(project)
    by_id = {f.id: f for f in draft.facts}
    return {
        entry: [by_id[i].model_dump() for i in ids if i in by_id]
        for entry, ids in draft.applied.items()
    }
