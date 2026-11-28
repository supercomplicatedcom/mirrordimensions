# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""Reading the seed folder, and nothing else (decision 0030, point 1).

The folder is the user's, so its files are untrusted: nothing found is run, no link is
followed out of the folder, and sizes, counts and depth are limited. Files are read as
bytes and decoded; nothing is executed or imported.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from mirrordimensions.errors import MirrorError

MAX_FILES = 5000
MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_TOTAL_BYTES = 200 * 1024 * 1024
MAX_DEPTH = 12
TEXT_SUFFIXES = frozenset({".md", ".markdown", ".txt", ".csv", ".json", ".yaml", ".yml"})


@dataclass(frozen=True)
class SeedFile:
    path: str  # relative to the folder, with forward slashes
    text: str


@dataclass
class Folder:
    root: Path
    files: list[SeedFile] = field(default_factory=list[SeedFile])
    repositories: list[str] = field(default_factory=list[str])  # folders holding .git
    skipped: list[tuple[str, str]] = field(default_factory=list[tuple[str, str]])  # path, why


def read_folder(root: Path) -> Folder:
    """Every readable text file under `root`, safely."""
    root = Path(root).expanduser()
    if root.is_symlink():
        raise MirrorError(
            "The seed folder is a link.",
            f"{root} points somewhere else.",
            "Name the folder itself, not a link to it.",
        )
    if not root.is_dir():
        raise MirrorError(
            "There is no seed folder there.",
            f"{root} is not a folder.",
            "Name a folder that holds the data the world should be built from.",
        )
    root = root.resolve()
    found = Folder(root=root)
    total = 0
    for current, dirs, names in os.walk(root, followlinks=False):
        here = Path(current)
        rel_dir = here.relative_to(root)
        depth = len(rel_dir.parts)
        if (here / ".git").exists():
            found.repositories.append(rel_dir.as_posix() if rel_dir.parts else ".")
            if rel_dir.parts:  # a repository is read as one, with its history, not file by file
                dirs[:] = []
                continue
        # Never descend into links, version-control internals or anything too deep.
        kept: list[str] = []
        for d in sorted(dirs):
            sub = here / d
            rel = (rel_dir / d).as_posix()
            if sub.is_symlink():
                found.skipped.append((rel, "a link, not followed"))
            elif d == ".git":
                continue
            elif depth + 1 > MAX_DEPTH:
                found.skipped.append((rel, "too deep"))
            else:
                kept.append(d)
        dirs[:] = kept
        for name in sorted(names):
            path = here / name
            rel = (rel_dir / name).as_posix()
            if path.is_symlink():
                found.skipped.append((rel, "a link, not followed"))
                continue
            if path.suffix.lower() not in TEXT_SUFFIXES:
                found.skipped.append((rel, "not a kind of file the mirror reads"))
                continue
            size = path.stat().st_size
            if size > MAX_FILE_BYTES:
                found.skipped.append((rel, f"larger than {MAX_FILE_BYTES // (1024 * 1024)} MB"))
                continue
            if len(found.files) >= MAX_FILES or total + size > MAX_TOTAL_BYTES:
                found.skipped.append((rel, "the folder's limit was reached"))
                continue
            raw = path.read_bytes()
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                found.skipped.append((rel, "not UTF-8 text"))
                continue
            total += size
            found.files.append(SeedFile(path=rel, text=text.replace("\r\n", "\n")))
    return found
