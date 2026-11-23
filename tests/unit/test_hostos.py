# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""Host portability: these run on Linux, macOS and Windows in CI."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mirrordimensions.errors import LockHeldError
from mirrordimensions.hostos.files import make_dir, owner_only_problem, write_bytes, write_text
from mirrordimensions.hostos.info import host_info
from mirrordimensions.hostos.lock import ProjectLock


def test_text_is_utf8_with_lf(tmp_path: Path) -> None:
    path = tmp_path / "out.txt"
    write_text(path, "Zürich\r\nKraków\rend\n")
    assert path.read_bytes() == "Zürich\nKraków\nend\n".encode()


def test_owner_only_file_and_folder(tmp_path: Path) -> None:
    folder = tmp_path / "secret"
    make_dir(folder, owner_only=True)
    key = folder / "key.pem"
    write_bytes(key, b"material", owner_only=True)
    assert owner_only_problem(folder) is None
    assert owner_only_problem(key) is None


def test_plain_file_is_not_owner_only(tmp_path: Path) -> None:
    path = tmp_path / "open.txt"
    write_text(path, "x")
    path.chmod(0o644)
    if host_info().os != "windows":
        assert owner_only_problem(path) is not None


def test_lock_names_the_holder(tmp_path: Path) -> None:
    with ProjectLock(tmp_path, "build"):
        holder = json.loads((tmp_path / "lock.json").read_text(encoding="utf-8"))
        assert holder["operation"] == "build"
        with pytest.raises(LockHeldError) as caught, ProjectLock(tmp_path, "run"):
            pass
        assert "`mirror build`" in caught.value.why
    # Released: it can be taken again, and the holder file is gone.
    assert not (tmp_path / "lock.json").exists()
    with ProjectLock(tmp_path, "run"):
        pass


def test_host_info_is_known() -> None:
    info = host_info()
    assert info.os in {"macos", "windows", "linux"}
    assert info.arch in {"arm64", "x64"}
