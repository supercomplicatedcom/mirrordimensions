# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""Git repositories in the seed folder, with their history (decision 0030, point 2).

Repositories are read with Dulwich, a pure-Python git reader: objects are read, never
checked out, so no hook, filter or configured command can run. A repository whose objects
live outside the seed folder (a `.git` file pointing elsewhere, or borrowed objects) is
refused, as a link out of the folder would be.
"""

from __future__ import annotations

from pathlib import Path

from dulwich.objects import Blob, Commit, Tree
from dulwich.repo import Repo
from pydantic import BaseModel, Field

from mirrordimensions.seed.detect import without_secrets

MAX_COMMITS = 300
MAX_BLOB_BYTES = 1024 * 1024
MAX_FILES = 2000


class SeedCommit(BaseModel):
    author: str | None = None
    message: str
    created: float
    files: dict[str, str | None] = Field(description="path -> new text, or None if deleted")


class SeedRepository(BaseModel):
    name: str
    description: str = ""
    language: str = ""
    commits: list[SeedCommit] = Field(default_factory=list[SeedCommit])


class Refused(Exception):
    """A repository the seed folder must not read."""


_LANGUAGES = {
    ".py": "Python",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".js": "JavaScript",
    ".go": "Go",
    ".java": "Java",
    ".kt": "Kotlin",
    ".rb": "Ruby",
    ".rs": "Rust",
    ".cs": "C#",
    ".php": "PHP",
    ".sql": "SQL",
    ".sh": "Shell",
    ".tf": "HCL",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".md": "Markdown",
    ".swift": "Swift",
    ".scala": "Scala",
    ".c": "C",
    ".cpp": "C++",
}


def _inside(root: Path, folder: Path) -> Path:
    """The repository's .git folder, refused if anything of it lies outside the seed folder."""
    dot_git = folder / ".git"
    if dot_git.is_symlink() or not dot_git.is_dir():
        raise Refused("its .git is a link or a file pointing elsewhere (a worktree or submodule)")
    alternates = dot_git / "objects" / "info" / "alternates"
    if alternates.is_file() and alternates.read_text(encoding="utf-8", errors="ignore").strip():
        raise Refused("it borrows objects from another repository")
    if not dot_git.resolve().is_relative_to(root):
        raise Refused("its .git is outside the seed folder")
    return dot_git


def _tree_files(repo: Repo, tree_id: bytes, prefix: str = "") -> dict[str, bytes]:
    """path -> blob id for every file in a tree (no links, no submodules)."""
    out: dict[str, bytes] = {}
    tree = repo[tree_id]
    if not isinstance(tree, Tree):
        return out
    for entry in tree.items():
        name = entry.path.decode("utf-8", errors="replace")
        path = f"{prefix}{name}"
        mode = entry.mode
        if mode & 0o170000 == 0o040000:  # a folder
            out |= _tree_files(repo, entry.sha, f"{path}/")
        elif mode & 0o170000 == 0o100000:  # a regular file; links and submodules are skipped
            out[path] = entry.sha
        if len(out) > MAX_FILES:
            break
    return out


def _text(repo: Repo, blob_id: bytes) -> tuple[str, int] | None:
    blob = repo[blob_id]
    if not isinstance(blob, Blob) or len(blob.data) > MAX_BLOB_BYTES or b"\0" in blob.data[:8000]:
        return None
    try:
        text = blob.data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    return without_secrets("", text)


def read_repository(root: Path, rel: str) -> tuple[SeedRepository, int]:
    """The repository at `rel` in the seed folder, its default branch's history oldest first,
    and how many lines holding a secret were left out of its files and messages."""
    folder = (root / rel).resolve()
    _inside(root, folder)
    repo = Repo(str(folder))
    try:
        head = repo.head()
    except KeyError:
        return SeedRepository(name=folder.name), 0
    chain: list[Commit] = []
    current: Commit | None = repo[head]  # type: ignore[assignment]
    while isinstance(current, Commit) and len(chain) < MAX_COMMITS:
        chain.append(current)
        current = repo[current.parents[0]] if current.parents else None  # type: ignore[assignment]
    chain.reverse()
    seen: dict[str, bytes] = {}
    commits: list[SeedCommit] = []
    dropped = 0
    for commit in chain:
        now = _tree_files(repo, commit.tree)
        changed: dict[str, str | None] = {}
        for path, blob_id in now.items():
            if seen.get(path) != blob_id:
                read = _text(repo, blob_id)
                if read is not None:
                    changed[path], lost = read
                    dropped += lost
        for path in set(seen) - set(now):
            changed[path] = None
        seen = now
        message, lost = without_secrets("", commit.message.decode("utf-8", errors="replace"))
        dropped += lost
        if not changed:
            continue
        commits.append(
            SeedCommit(
                author=commit.author.decode("utf-8", errors="replace").split(" <")[0] or None,
                message=message.strip() or "Update",
                created=float(commit.author_time),
                files=changed,
            )
        )
    counts: dict[str, int] = {}
    for path in seen:
        lang = _LANGUAGES.get(Path(path).suffix.lower())
        if lang and lang != "Markdown":
            counts[lang] = counts.get(lang, 0) + 1
    readme = next((p for p in seen if p.lower() in ("readme.md", "readme")), None)
    description = ""
    if readme and (read := _text(repo, seen[readme])):
        text = read[0]
        description = next(
            (
                line.strip("# ").strip()
                for line in text.split("\n")
                if line.strip() and not line.startswith("#")
            ),
            "",
        )[:120]
    return (
        SeedRepository(
            name=folder.name,
            description=description,
            language=max(counts, key=lambda k: counts[k]) if counts else "",
            commits=commits,
        ),
        dropped,
    )
