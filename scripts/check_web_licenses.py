# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""Fail if anything bundled into the portal's front end has a licence incompatible with
shipping under Apache-2.0.

Reads `src/mirrordimensions/portal/web/package-lock.json`: every package that is not a
development-only dependency ends up in the built files that ship inside the Python package.
Build and test tools (Vite, TypeScript, Playwright, axe) are not shipped and are not checked.
Fonts may be under the SIL Open Font License, which allows bundling them with any software
(decision 0017).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_licenses import classify

LOCK = Path(__file__).resolve().parent.parent / "src/mirrordimensions/portal/web/package-lock.json"
FONT_LICENCES = {"OFL-1.1"}
FONT_PACKAGES = ("@fontsource/",)


def main() -> int:
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    problems: list[str] = []
    count = 0
    for path, info in sorted(lock.get("packages", {}).items()):
        if not path or info.get("dev") or info.get("devOptional"):
            continue
        name = path.split("node_modules/")[-1]
        licence = str(info.get("license") or "")
        count += 1
        if licence in FONT_LICENCES and name.startswith(FONT_PACKAGES):
            outcome = "ok"
        else:
            outcome = classify(licence) if licence else "unknown"
        mark = "ok  " if outcome == "ok" else "FAIL"
        print(f"{mark}  {name:<34}{licence or 'no licence given'}")
        if outcome != "ok":
            problems.append(name)
    if problems:
        print(f"{len(problems)} bundled package(s) need review: {', '.join(problems)}")
        return 1
    print(f"ok    {count} bundled front-end packages have Apache-2.0-compatible licences")
    return 0


if __name__ == "__main__":
    sys.exit(main())
