# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""The CI checks fail when they should."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent.parent / "scripts"


def script(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("expression", "outcome"),
    [
        ("MIT", "ok"),
        ("Apache-2.0 OR BSD-3-Clause", "ok"),
        ("MPL-2.0", "ok"),
        ("GPL-3.0-or-later", "copyleft"),
        ("AGPL-3.0-only", "copyleft"),
        ("LGPL-2.1-or-later", "copyleft"),
        ("GPL-2.0-only OR MIT", "ok"),
        ("MIT AND GPL-3.0-only", "copyleft"),
        ("Proprietary", "unknown"),
    ],
)
def test_licence_classification(expression: str, outcome: str) -> None:
    assert script("check_licenses").classify(expression) == outcome


def test_import_boundary_catches_undeclared_and_os_checks(tmp_path: Path) -> None:
    mod = script("check_imports")
    src = tmp_path / "mirrordimensions"
    (src / "service").mkdir(parents=True)
    (src / "hostos").mkdir()
    (src / "service" / "bad.py").write_text(
        "import sys\nimport requests\nimport msvcrt\nif sys.platform == 'win32':\n    pass\n",
        encoding="utf-8",
    )
    (src / "hostos" / "fine.py").write_text(
        "import sys\nX = sys.platform\nimport fcntl\n", encoding="utf-8"
    )
    problems = mod.violations(src, {"pydantic"})
    text = "\n".join(problems)
    assert "imports 'requests', which is not a declared dependency" in text
    assert "service/bad.py:3: imports msvcrt" in text
    assert "service/bad.py:4: uses sys.platform" in text
    assert "hostos/fine.py" not in text


def test_real_package_passes_import_boundary() -> None:
    mod = script("check_imports")
    root = SCRIPTS.parent
    assert (
        mod.violations(
            root / "src" / "mirrordimensions", mod.declared_distributions(root / "pyproject.toml")
        )
        == []
    )


def test_dco(tmp_path: Path) -> None:
    mod = script("check_dco")

    def git(*args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=tmp_path, capture_output=True, text=True, check=True
        ).stdout

    git("init", "-q")
    git("config", "user.name", "Dana Okafor")
    git("config", "user.email", "dana@users.noreply.github.com")
    git("commit", "-q", "--allow-empty", "-m", "base")
    base = git("rev-parse", "HEAD").strip()
    git("commit", "-q", "--allow-empty", "-s", "-m", "signed")
    assert mod.check_range(base, "HEAD", cwd=tmp_path) == []
    git("commit", "-q", "--allow-empty", "-m", "unsigned")
    git(
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "wrong\n\nSigned-off-by: Someone <other@users.noreply.github.com>",
    )
    problems = mod.check_range(base, "HEAD", cwd=tmp_path)
    assert len(problems) == 2
    assert any("no 'Signed-off-by:'" in p for p in problems)
    assert any("but the author is dana@" in p for p in problems)


def test_spdx_header_check() -> None:
    mod = script("check_spdx")
    good = SCRIPTS / "check_spdx.py"
    assert mod.problem(good) is None
