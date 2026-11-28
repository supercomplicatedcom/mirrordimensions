# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""From a seed folder to what the world uses, and the review the user reads first
(decision 0030, points 2 to 5).

`read_seed` reads the folder once. What the world will use is kept in the project's
owner-only `.mirror/seed/content.json`, and every build reads that copy, never the folder:
the same copy and seed always build the same world.
"""

from __future__ import annotations

import csv
import fnmatch
import hashlib
import io
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
from ruamel.yaml import YAML

from mirrordimensions.config.common import StrictModel
from mirrordimensions.errors import MirrorError
from mirrordimensions.seed.chat import SeedChannel, from_mattermost, from_slack, slack_roots
from mirrordimensions.seed.detect import Personal, personal_in, without_secrets
from mirrordimensions.seed.reader import Folder, SeedFile, read_folder
from mirrordimensions.seed.repos import Refused, SeedRepository, read_repository
from mirrordimensions.seed.tickets import SeedTicket, from_csv, from_json

DOCUMENT_SUFFIXES = (".md", ".markdown", ".txt")
_NAME_COLUMNS = ("name", "full name", "full_name", "display name", "display_name")
_TICKET_COLUMNS = {"status", "summary", "description", "body", "issue", "state", "priority"}


class SeedPerson(BaseModel):
    name: str
    title: str | None = None
    department: str | None = None


class SeedDocument(BaseModel):
    path: str = Field(description="Where it goes in the handbook repository")
    title: str
    text: str


class SeedContent(BaseModel):
    """What the world uses from the seed folder. Kept owner-only; never reaches the agent
    as anything but ordinary world content."""

    version: int = 1
    digest: str = Field(description="Of everything below, so a change shows as pending")
    people: list[SeedPerson] = Field(default_factory=list[SeedPerson])
    documents: list[SeedDocument] = Field(default_factory=list[SeedDocument])
    tickets: list[SeedTicket] = Field(default_factory=list[SeedTicket])
    channels: list[SeedChannel] = Field(default_factory=list[SeedChannel])
    repositories: list[SeedRepository] = Field(default_factory=list[SeedRepository])
    tickets_repo: str | None = Field(
        default=None, description="Where tickets go that name no repository the world has"
    )


class ReviewItem(BaseModel):
    path: str
    kind: str
    becomes: str


class Dropped(BaseModel):
    path: str
    lines: int


class PersonalFound(BaseModel):
    path: str
    line: int
    kind: str
    shown: str


class SeedReview(BaseModel):
    """What the folder holds, what each item becomes, and what was left out or needs a yes."""

    folder: str
    items: list[ReviewItem] = Field(default_factory=list[ReviewItem])
    secrets_dropped: list[Dropped] = Field(default_factory=list[Dropped])
    personal: list[PersonalFound] = Field(default_factory=list[PersonalFound])
    not_read: list[tuple[str, str]] = Field(default_factory=list[tuple[str, str]])
    later: list[ReviewItem] = Field(
        default_factory=list[ReviewItem],
        description="Recognised, read by a later version (tickets, chat, repositories)",
    )
    personal_accepted: bool = False


class SeedSettings(StrictModel):
    """`seed.yaml` in the folder: how it builds, every time (decision 0030, point 4)."""

    leave_out: list[str] = Field(default_factory=list[str], description="Glob patterns")
    tickets_repo: str | None = Field(
        default=None,
        description="The repository for tickets that name none the world has (its usual "
        "name, such as billing-service, or the world's own)",
    )


def _settings(files: list[SeedFile]) -> SeedSettings:
    found = next((f for f in files if f.path == "seed.yaml"), None)
    if found is None:
        return SeedSettings()
    loaded: Any = YAML(typ="safe").load(found.text)  # pyright: ignore[reportUnknownMemberType]
    try:
        return SeedSettings.model_validate(loaded or {})
    except Exception as exc:  # pydantic's errors, reported to the user
        raise MirrorError(
            "seed.yaml in the seed folder is not valid.",
            str(exc)[:300],
            "Fix it: it may hold leave_out, a list of file patterns.",
        ) from exc


def _people(text: str) -> list[SeedPerson] | None:
    """A people CSV: a name column, and none of a ticket export's columns."""
    try:
        rows = list(csv.DictReader(io.StringIO(text)))
    except csv.Error:
        return None
    if not rows:
        return None
    columns = {c.strip().lower(): c for c in rows[0] if c}
    if _TICKET_COLUMNS & set(columns):
        return None
    name_col = next((columns[c] for c in _NAME_COLUMNS if c in columns), None)
    first = columns.get("first name") or columns.get("first_name") or columns.get("given name")
    last = columns.get("last name") or columns.get("last_name") or columns.get("family name")
    if name_col is None and not (first and last):
        return None
    title_col = next(
        (
            columns[c]
            for c in ("title", "job title", "job_title", "role", "position")
            if c in columns
        ),
        None,
    )
    dept_col = next(
        (columns[c] for c in ("department", "dept", "team", "group") if c in columns), None
    )
    people: list[SeedPerson] = []
    for row in rows:
        name = (row.get(name_col) or "").strip() if name_col else ""
        if not name and first and last:
            name = f"{(row.get(first) or '').strip()} {(row.get(last) or '').strip()}".strip()
        if len(name.split()) < 2:
            continue  # a person needs a first and a last name
        people.append(
            SeedPerson(
                name=re.sub(r"\s+", " ", name),
                title=(row.get(title_col) or "").strip() or None if title_col else None,
                department=(row.get(dept_col) or "").strip() or None if dept_col else None,
            )
        )
    return people or None


def _title(path: str, text: str) -> str:
    for line in text.split("\n"):
        if line.startswith("# "):
            return line[2:].strip()
    return Path(path).stem.replace("-", " ").replace("_", " ").strip().capitalize()


def _document_path(path: str) -> str:
    p = Path(path)
    stem = re.sub(r"[^a-z0-9]+", "-", p.stem.lower()).strip("-") or "page"
    parts = [re.sub(r"[^a-z0-9]+", "-", d.lower()).strip("-") for d in p.parent.parts]
    return "/".join(["docs", *[d for d in parts if d], f"{stem}.md"])


def read_seed(root: Path, company_domain: str) -> tuple[SeedContent, SeedReview]:
    """Read the folder once: what the world will use, and the review of it."""
    folder: Folder = read_folder(root)
    settings = _settings(folder.files)
    review = SeedReview(folder=str(folder.root), not_read=list(folder.skipped))
    people: list[SeedPerson] = []
    documents: list[SeedDocument] = []
    tickets: list[SeedTicket] = []
    channels: list[SeedChannel] = []
    consumed: set[str] = set()
    for export in slack_roots(folder.files):
        found_channels, used = from_slack(export, folder.files)
        consumed.update(used)
        channels.extend(found_channels)
        count = sum(len(c.messages) for c in found_channels)
        review.items.append(
            ReviewItem(
                path=export or ".",
                kind="Slack export",
                becomes=f"{len(found_channels)} channel(s), {count} message(s)",
            )
        )
        for path in used:
            text = next(f.text for f in folder.files if f.path == path)
            review.personal += [
                PersonalFound(path=p.path, line=p.line, kind=p.kind, shown=p.shown)
                for p in personal_in(path, text, company_domain)
            ]
    repositories: list[SeedRepository] = []
    for rel in folder.repositories:
        if rel == ".":
            review.not_read.append(
                (".", "the seed folder itself is a repository; put repositories in folders in it")
            )
            continue
        try:
            repo, lost = read_repository(folder.root, rel)
        except Refused as why:
            review.not_read.append((rel, f"repository not read: {why}"))
            continue
        if lost:
            review.secrets_dropped.append(Dropped(path=rel, lines=lost))
        repositories.append(repo)
        review.items.append(
            ReviewItem(
                path=rel,
                kind="git repository",
                becomes=f"repository {repo.name}, {len(repo.commits)} commit(s)",
            )
        )
        latest: dict[str, str | None] = {}
        for commit in repo.commits:
            latest.update(commit.files)
        for path, text in latest.items():
            if text:
                review.personal += [
                    PersonalFound(path=p.path, line=p.line, kind=p.kind, shown=p.shown)
                    for p in personal_in(f"{rel}/{path}", text, company_domain)
                ]
    for f in folder.files:
        if f.path == "seed.yaml" or f.path in consumed:
            continue
        if any(fnmatch.fnmatch(f.path, pattern) for pattern in settings.leave_out):
            review.not_read.append((f.path, "left out by seed.yaml"))
            continue
        suffix = Path(f.path).suffix.lower()
        # JSON is read whole and has secrets taken out value by value; other text line by line.
        text, dropped = (f.text, 0) if suffix == ".json" else without_secrets(f.path, f.text)
        if dropped:
            review.secrets_dropped.append(Dropped(path=f.path, lines=dropped))
        sheet = (
            from_json(f.text)
            if suffix == ".json"
            else from_csv(f.text)
            if suffix == ".csv"
            else None
        )
        posts = from_mattermost(f.text) if suffix == ".jsonl" else None
        if posts is not None:
            channels.extend(posts)
            count = sum(len(c.messages) for c in posts)
            review.items.append(
                ReviewItem(
                    path=f.path,
                    kind="Mattermost export",
                    becomes=f"{len(posts)} channel(s), {count} message(s)",
                )
            )
        elif sheet is not None:
            tickets.extend(sheet)
            review.items.append(
                ReviewItem(
                    path=f.path,
                    kind="tickets",
                    becomes=f"{len(sheet)} issue{'' if len(sheet) == 1 else 's'}",
                )
            )
        elif suffix == ".csv" and (found := _people(text)) is not None:
            people.extend(found)
            review.items.append(
                ReviewItem(path=f.path, kind="people", becomes=f"{len(found)} of the staff")
            )
        elif suffix in DOCUMENT_SUFFIXES:
            doc = SeedDocument(path=_document_path(f.path), title=_title(f.path, text), text=text)
            documents.append(doc)
            review.items.append(
                ReviewItem(path=f.path, kind="document", becomes=f"handbook page {doc.path}")
            )
        elif suffix in (".json", ".jsonl"):
            review.not_read.append((f.path, "JSON that is not tickets or a chat export"))
            continue
        else:
            review.not_read.append((f.path, "not a kind of file the mirror reads yet"))
            continue
        review.personal += [
            PersonalFound(path=p.path, line=p.line, kind=p.kind, shown=p.shown)
            for p in personal_in(f.path, text, company_domain)
        ]
    documents = _unique_paths(documents)
    body = SeedContent(
        digest="",
        people=people,
        documents=documents,
        tickets=tickets,
        channels=channels,
        repositories=repositories,
        tickets_repo=settings.tickets_repo,
    )
    digest = hashlib.sha256(body.model_dump_json().encode()).hexdigest()[:16]
    return body.model_copy(update={"digest": digest}), review


def _unique_paths(documents: list[SeedDocument]) -> list[SeedDocument]:
    seen: dict[str, int] = {}
    out: list[SeedDocument] = []
    for d in documents:
        key = d.path.lower()
        if key in seen:
            seen[key] += 1
            d = d.model_copy(update={"path": d.path[:-3] + f"-{seen[key]}.md"})
        else:
            seen[key] = 1
        out.append(d)
    return out


def personal_summary(review: SeedReview) -> list[Personal]:
    return [Personal(p.path, p.line, p.kind, p.shown) for p in review.personal]
