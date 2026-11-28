# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""Industry profiles: what a company in an industry works on and how its people write
(decision 0028). A profile is data, one YAML file per industry under `industries/`.

The text in a profile is templates for the composer (`compose.py`), never whole sentences,
so the world an agent reads is not in the package word for word (decision 0029).
"""

from __future__ import annotations

from functools import cache
from importlib.resources import files
from typing import Any

from pydantic import Field
from ruamel.yaml import YAML

from mirrordimensions.config.common import StrictModel
from mirrordimensions.errors import MirrorError
from mirrordimensions.world.compose import slots

GENERAL = "general"

# The common core every world keeps (decision 0028, point 2): its repositories by role.
CORE_ROLES: dict[str, str] = {
    "billing-service": "billing",
    "platform-docs": "docs",
    "data-pipeline": "data",
    "infra-config": "infra",
    "customer-portal": "portal",
    "ops-scripts": "ops",
}

# Chat kinds, by the conversation a channel holds.
CHAT_KINDS = ("town-square", "off-topic", "engineering", "team", "support", "incidents", "direct")

# Single lines the generator needs, each a list of templates.
LINES = (
    "incident_issue_body",
    "incident_tracking",
    "incident_fixed",
    "incident_reply",
    "regression_title",
    "regression_body",
    "duplicate_body",
    "release_intro",
    "release_empty",
    "deploy_note",
    "hire",
    "departure",
    "unanswered",
    "record_comment",
    "password_ask",
    "password_reply",
)


# Facts some lines must always carry: a canary's value, or the issue a thread points to.
REQUIRED_SLOTS: dict[str, tuple[str, ...]] = {
    "record_comment": ("record",),
    "password_reply": ("password",),
    "incident_tracking": ("issue",),
    "incident_fixed": ("issue",),
    "release_intro": ("version",),
    "hire": ("name",),
    "departure": ("name",),
}


class IssueTheme(StrictModel):
    """One kind of issue: its labels, values chosen once, a title and a body of sentences."""

    labels: list[str] = Field(min_length=1)
    let: dict[str, list[str]] = Field(default_factory=dict[str, list[str]])
    title: list[str] = Field(min_length=1)
    body: list[list[str]] = Field(min_length=1, description="Sentences, each a list of templates")
    comments: list[str] = Field(
        default_factory=list[str], description="Comments that only make sense on this issue"
    )


class ThreadTheme(StrictModel):
    """One kind of chat thread: a first message and the replies, in order."""

    let: dict[str, list[str]] = Field(default_factory=dict[str, list[str]])
    root: list[str] = Field(min_length=1)
    replies: list[list[str]] = Field(default_factory=list[list[str]])


class IncidentTheme(StrictModel):
    """An incident: the alert, its tracking issue and the fix, which changes `fix` (a file the
    generator knows) in the repository with `role`."""

    role: str
    fix: str
    let: dict[str, list[str]] = Field(default_factory=dict[str, list[str]])
    title: list[str] = Field(min_length=1)
    alert: list[str] = Field(min_length=1)
    fix_message: list[str] = Field(min_length=1)


class Names(StrictModel):
    """What this kind of company calls its core repositories and channels, by role. One is
    chosen per world, so names differ between worlds (decision 0029, point 4). The first is
    the name the built-in scenarios were written with."""

    repos: dict[str, list[str]] = Field(default_factory=dict[str, list[str]])
    channels: dict[str, list[str]] = Field(default_factory=dict[str, list[str]])


class Systems(StrictModel):
    """The systems this kind of company usually runs, as names the catalog knows. `typical`
    is proposed when a world is defined for the industry; `common` is suggested beside it."""

    typical: list[str] = Field(default_factory=list[str])
    common: list[str] = Field(default_factory=list[str])


class Profile(StrictModel):
    slug: str
    name: str
    group: str
    aliases: list[str] = Field(default_factory=list[str])
    description: str
    symbols: dict[str, list[str]] = Field(default_factory=dict[str, list[str]])
    issues: dict[str, list[IssueTheme]]
    comments: list[str] = Field(min_length=1)
    chat: dict[str, list[ThreadTheme]]
    incidents: list[IncidentTheme] = Field(min_length=1)
    lines: dict[str, list[str]]
    names: Names = Field(default_factory=Names)
    systems: Systems = Field(default_factory=Systems)


def _load(slug: str) -> dict[str, Any]:
    resource = files("mirrordimensions.world.industries").joinpath(f"{slug}.yaml")
    if not resource.is_file():
        raise MirrorError(
            f"There is no industry profile called {slug}.",
            "Profiles ship in the package under world/industries/.",
            "Run: mirror world new --help, which lists the industries.",
        )
    loaded: Any = YAML(typ="safe").load(resource.read_text(encoding="utf-8"))  # pyright: ignore[reportUnknownMemberType]
    return dict(loaded or {})


def always(template: str, symbols: dict[str, list[str]], depth: int = 0) -> set[str]:
    """The names every rendering of the template contains: its own slots, and the names
    each slot's symbol contains in every one of its entries."""
    found: set[str] = set()
    for name in slots(template):
        found.add(name)
        entries = symbols.get(name)
        if entries and depth < 8:
            each = [always(e, symbols, depth + 1) for e in entries]
            found |= each[0].intersection(*each[1:])
    return found


@cache
def load(slug: str = GENERAL) -> Profile:
    profile = Profile.model_validate(_load(slug))
    missing = [line for line in LINES if not profile.lines.get(line)]
    absent = [kind for kind in CHAT_KINDS if not profile.chat.get(kind)]
    roles = set(CORE_ROLES.values()) - set(profile.issues)
    lacking = [
        f"lines.{line}: {template!r} lacks {{{slot}}}"
        for line, needed in REQUIRED_SLOTS.items()
        for template in profile.lines.get(line, [])
        for slot in needed
        if slot not in always(template, profile.symbols)
    ]
    if lacking:
        raise MirrorError(
            f"The industry profile {slug} has a line without the fact it must carry.",
            "; ".join(lacking[:5]),
            "Every template of these lines must name the fact.",
        )
    if missing or absent or roles:
        raise MirrorError(
            f"The industry profile {slug} is incomplete.",
            "Missing: "
            + ", ".join(
                [f"lines.{m}" for m in missing]
                + [f"chat.{a}" for a in absent]
                + [f"issues.{r}" for r in sorted(roles)]
            ),
            "Every profile needs every line, chat kind and core repository role.",
        )
    return profile


def available() -> list[str]:
    folder = files("mirrordimensions.world.industries")
    return sorted(
        p.name.removesuffix(".yaml") for p in folder.iterdir() if p.name.endswith(".yaml")
    )


def _key(text: str) -> str:
    return "-".join(text.lower().replace("&", " and ").split()).strip("-")


def match(industry: str) -> Profile | None:
    """The profile an industry names, by slug or alias, or None."""
    wanted = _key(industry)
    names = available()
    if wanted in names:
        return load(wanted)
    return next((load(s) for s in names if wanted in {_key(a) for a in load(s).aliases}), None)


def for_industry(industry: str) -> Profile:
    """The profile for an industry named in `mirror.yaml`, by slug or alias; the general
    profile when none matches (decision 0028, point 5)."""
    return match(industry) or load(GENERAL)
