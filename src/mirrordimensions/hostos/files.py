# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""Portable file writing and owner-only permissions.

- Text is always UTF-8 with `\\n` line endings, written in binary mode, so the same
  content gives the same bytes on every host.
- Owner-only means POSIX modes 0600 and 0700 on macOS and Linux, and on Windows an
  access list that grants only the current user, with inheritance removed.
"""

from __future__ import annotations

import csv
import io
import os
import stat
import subprocess
from functools import cache
from pathlib import Path

from mirrordimensions.errors import MirrorError
from mirrordimensions.hostos.info import is_windows

# Windows principals that must never appear on an owner-only path.
_WIDE_PRINCIPALS = (
    "Everyone",
    "BUILTIN\\Users",
    "Authenticated Users",
    "NT AUTHORITY\\Authenticated Users",
)


def to_lf(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def write_text(path: Path, text: str, *, owner_only: bool = False) -> None:
    """Write `text` as UTF-8 with `\\n` line endings."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(to_lf(text).encode("utf-8"))
    if owner_only:
        set_owner_only(path)


def write_bytes(path: Path, data: bytes, *, owner_only: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if owner_only and not is_windows():
        # Create with the final mode so the content is never readable by others.
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.chmod(path, 0o600)
        return
    path.write_bytes(data)
    if owner_only:
        set_owner_only(path)


def make_dir(path: Path, *, owner_only: bool = False) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if owner_only:
        set_owner_only(path)


def set_owner_only(path: Path) -> None:
    if is_windows():
        _windows_restrict(path)
    else:
        os.chmod(path, 0o700 if path.is_dir() else 0o600)


def owner_only_problem(path: Path) -> str | None:
    """Return why `path` is not owner-only, or None if it is."""
    if is_windows():
        return _windows_problem(path)
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o077:
        return f"{path} has mode {oct(mode)}; group and others must have no access"
    return None


@cache
def _current_user_sid() -> str:
    result = _run(["whoami", "/user", "/fo", "csv", "/nh"])
    rows = list(csv.reader(io.StringIO(result)))
    if not rows or len(rows[0]) < 2:
        raise MirrorError(
            "Could not identify the current Windows user.",
            f"`whoami /user` printed: {result.strip()!r}",
            "Run the command from a normal user session and try again.",
        )
    return rows[0][1]


def _windows_restrict(path: Path) -> None:
    grant = f"*{_current_user_sid()}:(OI)(CI)F" if path.is_dir() else f"*{_current_user_sid()}:F"
    _run(["icacls", str(path), "/inheritance:r", "/grant:r", grant])


def _windows_problem(path: Path) -> str | None:
    listing = _run(["icacls", str(path)])
    if "(I)" in listing:
        return f"{path} inherits permissions from its parent folder"
    for principal in _WIDE_PRINCIPALS:
        if principal.lower() in listing.lower():
            return f"{path} grants access to {principal}"
    return None


def _run(args: list[str]) -> str:
    try:
        done = subprocess.run(args, capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise MirrorError(
            f"Could not run {args[0]}.",
            str(exc),
            "Check that the command is available and that you own the folder.",
        ) from exc
    return done.stdout
