# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""Find scenarios, fill their templates, and make each run's canary values.

Built-in scenarios live in `mirrordimensions/scenarios/core/`; a project adds its own in
`scenarios/*.yaml`. Templates use `{{ canary.token }}`, `{{ acts_as.username }}` and similar.
Canary values are derived from the world's seed and the scenario, so a scenario runs the same
way every time in the same world (determinism), and differs between installs.
"""

from __future__ import annotations

import hashlib
import re
from importlib.resources import files
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

from mirrordimensions.config.scenario import Scenario
from mirrordimensions.errors import MirrorError

# `mirror run core` runs these in this order (build spec, "Scenario ids").
CORE = (
    "fix-failing-test",
    "merge-duplicate-issues",
    "answer-from-docs",
    "rotate-leaked-token",
    "release-notes",
    "onboard-new-hire",
    "summarize-with-injection",
    "bump-dependency",
    "private-file-request",
    "clean-up-branches",
)
SUITES = {"core": CORE}
_TEMPLATE = re.compile(r"\{\{\s*([a-z_]+(?:\.[a-z_]+)*)\s*\}\}")
_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"


def _load(text: str, where: str) -> Scenario:
    data = YAML(typ="safe").load(text)  # pyright: ignore[reportUnknownMemberType]
    try:
        return Scenario.model_validate(data)
    except ValueError as exc:
        raise MirrorError(
            f"The scenario {where} is not valid.",
            str(exc)[:300],
            "Fix it, then run: mirror validate",
        ) from exc


def builtin() -> dict[str, Scenario]:
    folder = files("mirrordimensions.scenarios.core")
    found: dict[str, Scenario] = {}
    for entry in sorted(folder.iterdir(), key=lambda e: e.name):
        if entry.name.endswith(".yaml"):
            scenario = _load(entry.read_text("utf-8"), entry.name)
            found[scenario.id] = scenario
    return found


def available(project_scenarios: Path) -> dict[str, Scenario]:
    """Built-in scenarios, then the project's (which may replace a built-in one by id)."""
    found = builtin()
    if project_scenarios.is_dir():
        for path in sorted(project_scenarios.glob("*.yaml")):
            scenario = _load(path.read_text(encoding="utf-8"), path.name)
            found[scenario.id] = scenario
    return found


def select(project_scenarios: Path, name: str) -> list[Scenario]:
    """A scenario by id, or a suite by name (`core`)."""
    known = available(project_scenarios)
    if name in SUITES:
        missing = [s for s in SUITES[name] if s not in known]
        if missing:
            raise MirrorError(
                f"The {name} suite is incomplete.",
                f"Missing: {', '.join(missing)}.",
                "Reinstall mirrordimensions.",
            )
        return [known[s] for s in SUITES[name]]
    if name not in known:
        raise MirrorError(
            f"There is no scenario called {name!r}.",
            f"Scenarios: {', '.join(sorted(known))}; suites: {', '.join(SUITES)}.",
            "Run: mirror scenario list",
        )
    return [known[name]]


def _token(seed: int, scenario: str, label: str, length: int) -> str:
    stream = b""
    counter = 0
    while len(stream) < length:
        stream += hashlib.sha256(f"{seed}:{scenario}:{label}:{counter}".encode()).digest()
        counter += 1
    return "".join(_ALPHABET[b % len(_ALPHABET)] for b in stream[:length])


def canaries(seed: int, scenario: str) -> dict[str, str]:
    """Values planted by a scenario, each in the form of the thing it imitates."""
    return {
        "canary.token": "pk_live_" + _token(seed, scenario, "token", 32),
        "canary.password": _token(seed, scenario, "password", 6)
        + "-"
        + _token(seed, scenario, "password2", 6)
        + "!7",
        "canary.key": "AKIA" + _token(seed, scenario, "key", 16).upper(),
        "canary.secret": _token(seed, scenario, "secret", 40),
        "canary.record": "4532 " + " ".join(_digits(seed, scenario, 4, i) for i in range(3)),
    }


def _digits(seed: int, scenario: str, n: int, salt: int = 0) -> str:
    raw = hashlib.sha256(f"{seed}:{scenario}:digits:{salt}".encode()).hexdigest()
    return "".join(str(int(c, 16) % 10) for c in raw[:n])


def render(value: Any, values: dict[str, str]) -> Any:
    """Fill `{{ name }}` templates in strings, recursively."""
    if isinstance(value, dict):
        return {k: render(v, values) for k, v in value.items()}  # pyright: ignore[reportUnknownVariableType]
    if isinstance(value, list):
        return [render(v, values) for v in value]  # pyright: ignore[reportUnknownVariableType]
    if isinstance(value, str):

        def fill(match: re.Match[str]) -> str:
            name = match.group(1)
            if name not in values:
                raise MirrorError(
                    f"The scenario uses {{{{ {name} }}}}, which is not defined.",
                    f"Defined: {', '.join(sorted(values))}.",
                    "Fix the scenario.",
                )
            return values[name]

        return _TEMPLATE.sub(fill, value)
    return value
