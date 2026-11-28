# SPDX-License-Identifier: Apache-2.0
"""Helpers for the prototype exit gate (build spec, "Prototype exit gate").

`route <mirror.yaml>` adds the Anthropic model route `llm-example` needs, when the project
has none. `results <project>` checks the project's latest core runs: every core scenario
reached a scored result with a report, full isolation and complete coverage. The agent
need not pass them. Exits 1 with the reasons when any does not.
"""

# JSON from result files is untyped.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from mirrordimensions.runner.scenario import SUITES

ROUTE = """models:
- name: primary
  provider: anthropic
  host: api.anthropic.com
  credential: {from_env: ANTHROPIC_API_KEY}
"""


def route(manifest: Path) -> int:
    text = manifest.read_text("utf-8")
    if re.search(r"^models:\s*\[\]", text, re.MULTILINE) is None:
        print(f"{manifest} already declares model routes; left as it is")
        return 0
    manifest.write_text(
        re.sub(r"^models:\s*\[\].*\n", ROUTE, text, count=1, flags=re.MULTILINE), "utf-8"
    )
    print(f"added the anthropic route to {manifest}")
    return 0


def results(project: Path) -> int:
    latest: dict[str, tuple[str, dict[str, object], Path]] = {}
    for result in (project / ".mirror" / "runs").glob("*/result.json"):
        data = json.loads(result.read_text("utf-8"))
        name = str(data.get("scenario"))
        mtime = f"{result.stat().st_mtime:020.6f}"
        if name not in latest or mtime > latest[name][0]:
            latest[name] = (mtime, data, result.parent)
    problems: list[str] = []
    for name in SUITES["core"]:
        if name not in latest:
            problems.append(f"{name}: no run")
            continue
        _, data, folder = latest[name]
        coverage = data.get("coverage")
        covered = coverage.get("status") if isinstance(coverage, dict) else None
        print(
            f"{name:28} {data.get('status')!s:8} isolation {data.get('isolation')}"
            f" · coverage {covered} · {data.get('run_id')}"
        )
        if data.get("status") not in ("passed", "failed"):
            problems.append(f"{name}: {data.get('status')}, not scored")
        if data.get("isolation") != "full":
            problems.append(f"{name}: isolation {data.get('isolation')}")
        if covered != "complete":
            problems.append(f"{name}: coverage {covered}")
        if not (folder / "report.html").is_file():
            problems.append(f"{name}: no report.html")
    for problem in problems:
        print(f"fail  {problem}")
    if not problems:
        print(
            f"ok    all {len(SUITES['core'])} core scenarios scored, with reports,"
            " isolation full, coverage complete"
        )
    return 1 if problems else 0


def main(argv: list[str]) -> int:
    if len(argv) == 2 and argv[0] == "route":
        return route(Path(argv[1]))
    if len(argv) == 2 and argv[0] == "results":
        return results(Path(argv[1]))
    print("usage: exit_gate.py route <mirror.yaml> | results <project folder>", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
