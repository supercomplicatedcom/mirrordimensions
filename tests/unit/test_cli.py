# SPDX-License-Identifier: Apache-2.0
"""The command line: output rules and exit codes."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def mirror(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    env_free = [sys.executable, "-m", "mirrordimensions", *args]
    return subprocess.run(
        env_free, cwd=cwd, capture_output=True, text=True, check=False, encoding="utf-8"
    )


def test_help(tmp_path: Path) -> None:
    done = mirror("--help", cwd=tmp_path)
    assert done.returncode == 0
    for command in ("init", "validate", "schema", "status"):
        assert command in done.stdout


def test_init_then_validate(tmp_path: Path) -> None:
    done = mirror("init", "acme-free", "--seed", "48213", cwd=tmp_path)
    assert done.returncode == 0, done.stderr
    assert "Created acme-free/" in done.stdout
    assert "seed 48213" in done.stdout
    done = mirror("validate", cwd=tmp_path / "acme-free")
    assert done.returncode == 0
    assert done.stdout.startswith("ok")


def test_json_prints_one_document(project_dir: Path) -> None:
    done = mirror("--json", "status", cwd=project_dir)
    assert done.returncode == 0
    data = json.loads(done.stdout)
    assert data["state"] == "new"
    assert data["valid"] is True


def test_errors_have_three_parts_and_exit_2(tmp_path: Path) -> None:
    done = mirror("validate", cwd=tmp_path)
    assert done.returncode == 2
    assert done.stdout == ""
    lines = done.stderr.strip().splitlines()
    assert lines[0] == "No project here."
    assert lines[2].startswith("Run: mirror init")


def test_failed_validation_exits_1(project_dir: Path) -> None:
    (project_dir / "mirror.yaml").write_bytes(b"version: 2\n")
    done = mirror("validate", cwd=project_dir)
    assert done.returncode == 1
    assert done.stdout.startswith("FAIL")


def test_schema_prints_json(tmp_path: Path) -> None:
    done = mirror("schema", "event", cwd=tmp_path)
    assert json.loads(done.stdout)["title"] == "Event"


def test_output_is_utf8_on_every_host(tmp_path: Path) -> None:
    done = subprocess.run(
        [sys.executable, "-m", "mirrordimensions", "init", "plain", "--seed", "48213"],
        cwd=tmp_path,
        capture_output=True,
        check=False,
    )
    assert done.returncode == 0
    assert " · ".encode() in done.stdout


def test_no_color_when_not_a_terminal(project_dir: Path) -> None:
    done = mirror("validate", cwd=project_dir)
    assert "\033[" not in done.stdout
