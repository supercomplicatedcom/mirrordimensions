# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""Load and search the catalog. Names resolve through slugs and aliases, ignoring case and
punctuation; unknown names are reported, never guessed (build spec, "App catalog")."""

from __future__ import annotations

import csv
import re
from functools import cache
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field
from ruamel.yaml import YAML

from mirrordimensions.errors import MirrorError

Status = Literal["candidate", "specified", "buildable", "verified"]

CATEGORY_KINDS = {
    "Work suites and collaboration": "collaboration",
    "Software development": "developer-tool",
    "Project and work management": "ticketing",
    "CRM and sales": "crm",
    "HR and people": "hr",
    "Finance, ERP and procurement": "erp",
    "Customer support and contact center": "helpdesk",
    "IT service and device management": "itsm",
    "Identity and access": "identity",
    "Security": "security",
    "Observability and incident response": "observability",
    "Cloud platforms and data infrastructure": "cloud",
    "Data, analytics and AI": "analytics",
    "Marketing": "marketing",
    "Legal, contracts and records": "legal",
    "Automation and low-code": "automation",
    "Industry and operations": "operations",
    "Buildings, networks and connected devices": "devices",
}


class Entry(BaseModel):
    slug: str
    name: str
    aliases: list[str] = Field(default_factory=list[str])
    category: str
    kind: str
    tier: int
    hostname_pattern: str | None = None
    interfaces: list[str] = Field(default_factory=list[str])
    vendor_sandbox: Literal["yes", "no", "unknown"] = "unknown"
    twin_status: Status = "candidate"
    twin: str | None = None
    verified: bool = False


class Match(BaseModel):
    query: str
    entry: Entry | None
    buildable: bool
    instead: Entry | None = None  # the system with a twin of the same kind, when this has none


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def catalog_dir() -> Path:
    """The catalog ships beside the package in a source checkout."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "catalog" / "apps.csv").is_file():
            return parent / "catalog"
    raise MirrorError(
        "The app catalog is missing.",
        "catalog/apps.csv was not found.",
        "Reinstall MirrorDimensions.",
    )


@cache
def load(directory: Path | None = None) -> tuple[Entry, ...]:
    folder = directory or catalog_dir()
    loaded: Any = YAML(typ="safe").load((folder / "overrides.yaml").read_text(encoding="utf-8"))  # pyright: ignore[reportUnknownMemberType]
    overrides: dict[str, dict[str, Any]] = dict(loaded or {})
    entries: dict[str, Entry] = {}
    with (folder / "apps.csv").open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            slug = slugify(row["name"])
            entries[slug] = Entry(
                slug=slug,
                name=row["name"],
                category=row["category"],
                kind=CATEGORY_KINDS.get(row["category"], "other"),
                tier=int(row["tier"]),
                twin_status=_status(row["twin_status"]),
                verified=row["verified"] == "yes",
            )  # type: ignore[arg-type]
    for slug, extra in overrides.items():
        if slug in entries:
            entries[slug] = entries[slug].model_copy(update=extra)
        else:
            entries[slug] = Entry(slug=slug, **extra)
    return tuple(sorted(entries.values(), key=lambda e: (e.tier, e.slug)))


def _status(value: str) -> Status:
    if value not in ("candidate", "specified", "buildable", "verified"):
        raise MirrorError(
            f"Unknown catalog status {value!r}.", "catalog/apps.csv has a bad row.", "Fix the row."
        )
    return value  # type: ignore[return-value]


@cache
def _lookup(directory: Path | None = None) -> dict[str, Entry]:
    table: dict[str, Entry] = {}
    for entry in load(directory):
        for key in (entry.slug, entry.name, *entry.aliases):
            table.setdefault(normalize(key), entry)
    return table


def resolve(name: str) -> Entry | None:
    return _lookup().get(normalize(name))


def _buildable(entry: Entry | None) -> bool:
    return bool(entry and entry.twin_status in ("buildable", "verified"))


def twin_for_kind(kind: str) -> Entry | None:
    """The system the mirror can run for this kind of system (Gitea for code hosting, say)."""
    return next((e for e in load() if e.kind == kind and _buildable(e)), None)


def match_systems(names: list[str]) -> list[Match]:
    out: list[Match] = []
    for name in names:
        entry = resolve(name)
        buildable = _buildable(entry)
        instead = twin_for_kind(entry.kind) if entry and not buildable else None
        out.append(Match(query=name, entry=entry, buildable=buildable, instead=instead))
    return out


def search(text: str, limit: int = 20) -> list[Entry]:
    key = normalize(text)
    exact = resolve(text)
    hits = [exact] if exact else []
    for entry in load():
        if entry in hits:
            continue
        if (
            key in normalize(entry.name)
            or any(key in normalize(a) for a in entry.aliases)
            or key in entry.kind
        ):
            hits.append(entry)
    return hits[:limit]


def stats() -> dict[str, object]:
    entries = load()
    by_status: dict[str, int] = {}
    by_tier: dict[int, int] = {}
    for e in entries:
        by_status[e.twin_status] = by_status.get(e.twin_status, 0) + 1
        by_tier[e.tier] = by_tier.get(e.tier, 0) + 1
    return {
        "entries": len(entries),
        "by_status": by_status,
        "by_tier": dict(sorted(by_tier.items())),
        "categories": len({e.category for e in entries}),
    }


def collisions() -> list[str]:
    """Aliases or names that resolve to more than one entry: CI fails on any."""
    seen: dict[str, str] = {}
    out: list[str] = []
    for entry in load():
        for key in {normalize(k) for k in (entry.slug, entry.name, *entry.aliases)}:
            if key in seen and seen[key] != entry.slug:
                out.append(f"{key!r}: {seen[key]} and {entry.slug}")
            seen.setdefault(key, entry.slug)
    return out
