# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""Tickets from the seed folder: a hand-made CSV, or an export from Jira, GitHub, GitLab or
Linear, recognised by its columns or keys (decision 0030, point 2).

Every format is read into one shape. Dates are kept as found; the generator moves them onto
the world's timeline, keeping their spacing.
"""

# Exports are loosely shaped JSON: values are checked as they are read, not typed ahead.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

from __future__ import annotations

import csv
import io
import json
from datetime import UTC, datetime
from typing import Any, cast

from pydantic import BaseModel, Field

from mirrordimensions.seed.detect import without_secrets


class SeedComment(BaseModel):
    author: str | None = None
    body: str
    created: float | None = Field(default=None, description="Seconds since the epoch")


class SeedTicket(BaseModel):
    title: str
    body: str = ""
    closed: bool = False
    labels: list[str] = Field(default_factory=list[str])
    author: str | None = None
    assignee: str | None = None
    repo: str | None = Field(default=None, description="The repository or project it names")
    created: float | None = None
    closed_at: float | None = None
    comments: list[SeedComment] = Field(default_factory=list[SeedComment])


_TITLE = ("title", "summary", "subject", "name", "issue title")
_BODY = ("description", "body", "details", "text", "issue description")
_STATE = ("status", "state", "resolution")
_LABELS = ("labels", "label", "tags", "type", "issue type", "priority")
_ASSIGNEE = ("assignee", "assigned to", "owner")
_AUTHOR = ("reporter", "author", "created by", "creator", "opened by")
_REPO = ("repository", "repo", "project", "component", "components", "team")
_CREATED = ("created", "created at", "created_at", "opened", "date", "created date")
_CLOSED_AT = ("resolved", "closed", "closed at", "closed_at", "resolution date", "completed at")
_DONE = {
    "done",
    "closed",
    "resolved",
    "complete",
    "completed",
    "fixed",
    "cancelled",
    "canceled",
    "won't fix",
    "wont fix",
    "duplicate",
    "merged",
}


def _when(value: Any) -> float | None:
    """A date in any of the usual export forms, as seconds since the epoch, or None."""
    if value in (None, ""):
        return None
    if isinstance(value, int | float):
        return float(value) / (1000 if value > 1e11 else 1)
    text = str(value).strip().replace("Z", "+00:00")
    for form in (
        None,
        "%d/%b/%y %I:%M %p",
        "%d/%b/%Y %I:%M %p",
        "%Y-%m-%d %H:%M",
        "%m/%d/%Y",
        "%d/%m/%Y",
        "%Y/%m/%d",
        "%b %d, %Y",
    ):
        try:
            parsed = datetime.fromisoformat(text) if form is None else datetime.strptime(text, form)
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.timestamp()
    return None


def _pick(row: dict[str, Any], names: tuple[str, ...]) -> Any:
    lowered = {str(k).strip().lower(): v for k, v in row.items()}
    for name in names:
        if lowered.get(name) not in (None, ""):
            return lowered[name]
    return None


def _clean(text: Any) -> str:
    return without_secrets("", str(text or ""))[0].strip()


def _labels(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    items = value if isinstance(value, list) else str(value).replace(";", ",").split(",")
    out: list[str] = []
    for item in cast(list[Any], items):
        name = item.get("name") if isinstance(item, dict) else item
        text = str(name or "").strip().lower().replace(" ", "-")
        if text and text not in out:
            out.append(text)
    return out


def from_csv(text: str) -> list[SeedTicket] | None:
    """A ticket sheet: a title column and at least one of status, description or priority."""
    try:
        rows = list(csv.DictReader(io.StringIO(text)))
    except csv.Error:
        return None
    if not rows:
        return None
    columns = {str(c).strip().lower() for c in rows[0] if c}
    if not (set(_TITLE) & columns) or not ({*_STATE, *_BODY, "priority"} & columns):
        return None
    tickets: list[SeedTicket] = []
    for row in rows:
        title = _clean(_pick(row, _TITLE))
        if not title:
            continue
        state = str(_pick(row, _STATE) or "").strip().lower()
        comment_cells = [
            v for k, v in row.items() if k and k.strip().lower().startswith("comment") and v
        ]
        tickets.append(
            SeedTicket(
                title=title,
                body=_clean(_pick(row, _BODY)),
                closed=state in _DONE,
                labels=_labels(_pick(row, _LABELS)),
                author=_name(_pick(row, _AUTHOR)),
                assignee=_name(_pick(row, _ASSIGNEE)),
                repo=_name(_pick(row, _REPO)),
                created=_when(_pick(row, _CREATED)),
                closed_at=_when(_pick(row, _CLOSED_AT)),
                comments=[SeedComment(body=_clean(c)) for c in comment_cells if _clean(c)],
            )
        )
    return tickets or None


def _name(value: Any) -> str | None:
    if isinstance(value, dict):
        value = (
            cast(dict[str, Any], value).get("displayName")
            or value.get("name")
            or value.get("login")
        )
    text = str(value or "").strip()
    return text or None


def _comments(items: Any) -> list[SeedComment]:
    out: list[SeedComment] = []
    for c in cast(list[Any], items or []):
        if not isinstance(c, dict):
            continue
        c = cast(dict[str, Any], c)
        body = _clean(c.get("body") or c.get("text") or c.get("note"))
        if body:
            out.append(
                SeedComment(
                    author=_name(c.get("author") or c.get("user")),
                    body=body,
                    created=_when(c.get("created") or c.get("created_at") or c.get("createdAt")),
                )
            )
    return out


def _jira(issue: dict[str, Any]) -> SeedTicket | None:
    f = cast(dict[str, Any], issue.get("fields") or {})
    title = _clean(f.get("summary"))
    if not title:
        return None
    status = cast(dict[str, Any], f.get("status") or {})
    category = cast(dict[str, Any], status.get("statusCategory") or {})
    comment = cast(dict[str, Any], f.get("comment") or {})
    project = cast(dict[str, Any], f.get("project") or {})
    return SeedTicket(
        title=title,
        body=_clean(f.get("description")),
        closed=str(category.get("key", "")).lower() == "done"
        or str(status.get("name", "")).lower() in _DONE,
        labels=_labels(f.get("labels"))
        + _labels(cast(dict[str, Any], f.get("issuetype") or {}).get("name")),
        author=_name(f.get("reporter")),
        assignee=_name(f.get("assignee")),
        repo=_name(project.get("key") or project.get("name")),
        created=_when(f.get("created")),
        closed_at=_when(f.get("resolutiondate")),
        comments=_comments(comment.get("comments")),
    )


def _flat(issue: dict[str, Any]) -> SeedTicket | None:
    """GitHub, GitLab and Linear exports: one object per issue, with a title."""
    title = _clean(issue.get("title"))
    if not title:
        return None
    state = issue.get("state")
    state_name = str(
        cast(dict[str, Any], state).get("name") if isinstance(state, dict) else state or ""
    )
    labels = issue.get("labels")
    if isinstance(labels, dict):
        labels = cast(dict[str, Any], labels).get("nodes")
    return SeedTicket(
        title=title,
        body=_clean(issue.get("body") or issue.get("description")),
        closed=state_name.lower() in _DONE
        or bool(issue.get("closed_at") or issue.get("completedAt")),
        labels=_labels(labels),
        author=_name(issue.get("user") or issue.get("author") or issue.get("creator")),
        assignee=_name(issue.get("assignee") or (issue.get("assignees") or [None])[0]),
        repo=_name(issue.get("repository") or issue.get("project") or issue.get("team")),
        created=_when(issue.get("created_at") or issue.get("createdAt")),
        closed_at=_when(issue.get("closed_at") or issue.get("completedAt")),
        comments=_comments(
            issue.get("comments") if isinstance(issue.get("comments"), list) else []
        ),
    )


def from_json(text: str) -> list[SeedTicket] | None:
    """A Jira export ({"issues": [...]} with `fields`), or a list of GitHub, GitLab or Linear
    issues. None if the file is neither."""
    try:
        data: Any = json.loads(text)
    except json.JSONDecodeError:
        return None
    items: Any = data.get("issues") if isinstance(data, dict) else data
    if isinstance(data, dict) and items is None:
        items = cast(dict[str, Any], data).get("nodes") or cast(dict[str, Any], data).get("data")
    if not isinstance(items, list) or not items:
        return None
    tickets: list[SeedTicket] = []
    for raw in cast(list[Any], items):
        if not isinstance(raw, dict):
            return None
        item = cast(dict[str, Any], raw)
        ticket = _jira(item) if "fields" in item else _flat(item)
        if ticket is not None:
            tickets.append(ticket)
    return tickets or None
