# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""A world built from a seed folder the user chooses (decision 0030).

The folder is read once, when the user names it. What the world uses is copied into the
project's owner-only `.mirror/seed/`, beside the review of it; every build reads the copy.
Nothing here is reachable from the sandbox.
"""

from __future__ import annotations

from pathlib import Path

from mirrordimensions.config.loader import load_model
from mirrordimensions.config.manifest import Manifest
from mirrordimensions.errors import MirrorError
from mirrordimensions.hostos.files import make_dir, write_text
from mirrordimensions.project import Project
from mirrordimensions.seed.content import SeedContent, SeedReview, read_seed


def _dir(project: Project) -> Path:
    return project.state_dir / "seed"


def seed_world(
    project: Project, folder: Path, accept_personal: bool = False, strict: bool = True
) -> SeedReview:
    """Read the seed folder, keep what the world will use, and return the review. Personal
    data found in it must be accepted first (decision 0030, point 5): until it is, nothing
    from the folder is used, and `strict` raises to say so."""
    folder = Path(folder).expanduser().resolve()
    manifest, problems = load_model(project.manifest_path, Manifest)
    if manifest is None:
        raise MirrorError(
            "mirror.yaml is not valid, so the seed folder was not read.",
            "; ".join(p.message for p in problems[:3]),
            "Fix it first: mirror validate",
        )
    content, review = read_seed(folder, manifest.company.domain)
    review.personal_accepted = accept_personal or not review.personal
    make_dir(_dir(project), owner_only=True)
    write_text(
        _dir(project) / "review.json", review.model_dump_json(indent=2) + "\n", owner_only=True
    )
    if not review.personal_accepted:
        (_dir(project) / "content.json").unlink(missing_ok=True)
        if not strict:
            return review
        raise MirrorError(
            "The seed folder holds what looks like personal data.",
            f"{len(review.personal)} item(s), listed by file and line in: mirror world seed show.",
            "Remove them from the folder and read it again, or, if it is test data, accept it: "
            f"mirror world seed {folder} --accept-personal-data",
        )
    write_text(
        _dir(project) / "content.json", content.model_dump_json(indent=2) + "\n", owner_only=True
    )
    return review


def load_content(project: Project) -> SeedContent | None:
    """What the world uses from its seed folder, or None for a world without one."""
    path = _dir(project) / "content.json"
    if not path.is_file():
        return None
    return SeedContent.model_validate_json(path.read_text(encoding="utf-8"))


def load_review(project: Project) -> SeedReview | None:
    path = _dir(project) / "review.json"
    if not path.is_file():
        return None
    return SeedReview.model_validate_json(path.read_text(encoding="utf-8"))


def seeded_texts(project: Project) -> frozenset[str]:
    """The user's own texts, left out of the public-text share (decision 0030, point 9)."""
    content = load_content(project)
    if content is None:
        return frozenset()
    texts = {d.text for d in content.documents}
    for ticket in content.tickets:  # as the check reads an issue: its title, then its body
        texts.add(f"{ticket.title}. {ticket.body}")
        texts.update(c.body for c in ticket.comments)
    texts.update(m.text for c in content.channels for m in c.messages)
    for repo in content.repositories:
        for commit in repo.commits:
            texts.add(commit.message)
            texts.update(text for text in commit.files.values() if text)
    return frozenset(texts)
