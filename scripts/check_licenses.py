# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""Fail if any runtime dependency, direct or transitive, has a licence incompatible with
shipping under Apache-2.0.

The licence is read from package metadata: `License-Expression` (PEP 639) first, then
the `License` field, then trove classifiers. Copyleft licences fail. Unknown licences fail
too, until reviewed and listed in REVIEWED with a reason.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, distribution
from typing import Literal

ROOT_PACKAGE = "mirrordimensions"

PERMISSIVE = {
    "MIT",
    "MIT-0",
    "BSD-2-Clause",
    "BSD-3-Clause",
    "0BSD",
    "Apache-2.0",
    "ISC",
    "PSF-2.0",
    "Python-2.0",
    "Unlicense",
    "Zlib",
    "CC0-1.0",
    # Weak, file-level copyleft: using an unmodified library is compatible with Apache-2.0.
    "MPL-2.0",
}
COPYLEFT = re.compile(r"\b(A?GPL|LGPL|SSPL|BUSL|EUPL|CDDL|OSL|CPAL|EPL|Commons Clause)\b", re.I)

CLASSIFIER_MAP = {
    "MIT License": "MIT",
    "BSD License": "BSD-3-Clause",
    "Apache Software License": "Apache-2.0",
    "ISC License (ISCL)": "ISC",
    "Python Software Foundation License": "PSF-2.0",
    "Mozilla Public License 2.0 (MPL 2.0)": "MPL-2.0",
    "The Unlicense (Unlicense)": "Unlicense",
}
TEXT_MAP = {
    "mit": "MIT",
    "mit license": "MIT",
    "bsd": "BSD-3-Clause",
    "bsd license": "BSD-3-Clause",
    "bsd-3-clause": "BSD-3-Clause",
    "3-clause bsd license": "BSD-3-Clause",
    "apache 2.0": "Apache-2.0",
    "apache-2.0": "Apache-2.0",
    "apache license 2.0": "Apache-2.0",
    "isc": "ISC",
    "isc license": "ISC",
    "isc license (iscl)": "ISC",
    "psf": "PSF-2.0",
    "mpl-2.0": "MPL-2.0",
}

# Packages whose metadata is unclear, checked by hand. Each entry needs a reason.
REVIEWED: dict[str, str] = {}


@dataclass
class Verdict:
    package: str
    licence: str
    outcome: Literal["ok", "copyleft", "unknown"]


def classify(expression: str) -> Literal["ok", "copyleft", "unknown"]:
    """Classify an SPDX expression or licence name. `A OR B` passes if either passes."""
    if COPYLEFT.search(expression) and " OR " not in expression.upper():
        return "copyleft"
    alternatives = re.split(r"\s+OR\s+", expression.strip("() "), flags=re.I)
    outcomes: list[str] = []
    for alt in alternatives:
        parts = [p.strip("() ") for p in re.split(r"\s+AND\s+", alt, flags=re.I)]
        if all(p in PERMISSIVE for p in parts):
            return "ok"
        outcomes.append("copyleft" if any(COPYLEFT.search(p) for p in parts) else "unknown")
    return "copyleft" if all(o == "copyleft" for o in outcomes) else "unknown"


def licence_of(name: str) -> str:
    meta = distribution(name).metadata
    expression = meta.get("License-Expression")
    if expression:
        return expression
    text = (meta.get("License") or "").strip()
    if text and len(text) < 80:
        return TEXT_MAP.get(text.lower(), text)
    for classifier in meta.get_all("Classifier") or []:
        if classifier.startswith("License :: OSI Approved :: "):
            label = classifier.rsplit(" :: ", 1)[-1]
            return CLASSIFIER_MAP.get(label, label)
    return "UNKNOWN"


def requirement_names(name: str) -> list[str]:
    out: list[str] = []
    for req in distribution(name).requires or []:
        if "extra ==" in req:
            continue
        match = re.match(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)", req)
        if match:
            out.append(match.group(1))
    return out


def runtime_closure(root: str) -> list[str]:
    seen: set[str] = set()
    todo = [root]
    while todo:
        name = todo.pop()
        key = name.lower().replace("_", "-")
        if key in seen:
            continue
        seen.add(key)
        try:
            todo += requirement_names(name)
        except PackageNotFoundError:
            continue  # a dependency for another platform or Python version
    seen.discard(root)
    return sorted(seen)


def main() -> int:
    verdicts: list[Verdict] = []
    for name in runtime_closure(ROOT_PACKAGE):
        try:
            lic = licence_of(name)
        except PackageNotFoundError:
            continue
        outcome = "ok" if name in REVIEWED else classify(lic)
        verdicts.append(Verdict(name, lic, outcome))
    bad = [v for v in verdicts if v.outcome != "ok"]
    for v in verdicts:
        print(f"{'ok' if v.outcome == 'ok' else 'FAIL':<6}{v.package:<28}{v.licence}")
    if bad:
        print(f"{len(bad)} dependency licence(s) need review; see CONTRIBUTING.md, Dependencies")
        return 1
    print(f"ok    {len(verdicts)} runtime dependencies have Apache-2.0-compatible licences")
    return 0


if __name__ == "__main__":
    sys.exit(main())
