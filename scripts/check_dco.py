# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""Every non-merge commit in a range carries a DCO sign-off matching its author.

Usage: python scripts/check_dco.py <base> <head>
       python scripts/check_dco.py --message-file <path>   (commit-msg hook)
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

SIGNOFF = re.compile(r"^Signed-off-by: (?P<name>.+?) <(?P<email>[^>]+)>\s*$", re.M)


def signoffs(message: str) -> list[tuple[str, str]]:
    return [(m["name"], m["email"].lower()) for m in SIGNOFF.finditer(message)]


def commit_problem(sha: str, author_email: str, message: str) -> str | None:
    emails = [email for _, email in signoffs(message)]
    if not emails:
        return f"{sha[:12]}: no 'Signed-off-by:' line (commit with: git commit -s)"
    if author_email.lower() not in emails:
        return f"{sha[:12]}: signed off by {', '.join(emails)}, but the author is {author_email}"
    return None


def check_range(base: str, head: str, cwd: Path | None = None) -> list[str]:
    log = subprocess.run(
        ["git", "log", "--no-merges", "--format=%H%x1f%ae%x1f%B%x1e", f"{base}..{head}"],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    problems: list[str] = []
    for record in log.split("\x1e"):
        record = record.strip("\n")
        if not record:
            continue
        sha, email, message = record.split("\x1f", 2)
        problem = commit_problem(sha, email, message)
        if problem:
            problems.append(problem)
    return problems


def main(argv: list[str]) -> int:
    if len(argv) == 2 and argv[0] == "--message-file":
        message = Path(argv[1]).read_text(encoding="utf-8")
        if signoffs(message):
            return 0
        print("This commit has no DCO sign-off. Commit with: git commit -s")
        return 1
    if len(argv) != 2:
        print(__doc__)
        return 2
    problems = check_range(argv[0], argv[1])
    for problem in problems:
        print(problem)
    if problems:
        print(f"{len(problems)} commit(s) without a matching DCO sign-off")
        return 1
    print("ok    every commit has a DCO sign-off matching its author")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
