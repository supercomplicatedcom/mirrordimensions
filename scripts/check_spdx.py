# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""Every source file carries an SPDX copyright line and the Apache-2.0 licence identifier.

Checked in the first five lines, so a shebang or encoding line may come first.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXTENSIONS = {".py", ".ts", ".tsx", ".js", ".sh", ".toml", ".yml", ".yaml"}
SKIP_PREFIXES = ("tests/golden/", "tests/fixtures/")
SKIP_FILES = {"uv.lock", ".python-version"}

COPYRIGHT = re.compile(r"SPDX-FileCopyrightText: (19|20)\d\d\b.+")
LICENCE = re.compile(r"SPDX-License-Identifier: Apache-2\.0\s*$")


def tracked_files() -> list[str]:
    done = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in done.stdout.splitlines() if line]


def problem(path: Path) -> str | None:
    head = path.read_text(encoding="utf-8", errors="replace").splitlines()[:5]
    if not any(COPYRIGHT.search(line) for line in head):
        return "missing 'SPDX-FileCopyrightText: <year> <holder>' in the first five lines"
    if not any(LICENCE.search(line) for line in head):
        return "missing 'SPDX-License-Identifier: Apache-2.0' in the first five lines"
    return None


def main() -> int:
    failures: list[str] = []
    for name in tracked_files():
        if name in SKIP_FILES or name.startswith(SKIP_PREFIXES):
            continue
        path = ROOT / name
        if path.suffix not in EXTENSIONS or not path.is_file():
            continue
        reason = problem(path)
        if reason:
            failures.append(f"{name}: {reason}")
    for failure in failures:
        print(failure)
    if failures:
        print(f"{len(failures)} file(s) without licence headers")
        return 1
    print("ok    every source file has SPDX licence headers")
    return 0


if __name__ == "__main__":
    sys.exit(main())
