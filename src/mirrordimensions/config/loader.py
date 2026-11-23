# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""Load YAML files into the typed formats, reporting problems with file and line."""

# ruamel.yaml's round-trip types are only partly annotated.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ValidationError
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.error import MarkedYAMLError


class Problem(BaseModel):
    file: str
    line: int | None = None
    message: str
    severity: Literal["error", "warning"] = "error"

    def render(self) -> str:
        where = f"{self.file}:{self.line}" if self.line else self.file
        return f"{where}: {self.message}"


def _yaml() -> YAML:
    yaml = YAML(typ="rt")
    yaml.preserve_quotes = True
    return yaml


def read_yaml(path: Path) -> tuple[Any, list[Problem]]:
    """Parse a YAML file, keeping comments and positions."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, [Problem(file=str(path), message=f"cannot read: {exc.strerror}")]
    try:
        return _yaml().load(text), []
    except MarkedYAMLError as exc:
        line = exc.problem_mark.line + 1 if exc.problem_mark is not None else None
        return None, [Problem(file=str(path), line=line, message=f"not valid YAML: {exc.problem}")]


def _line_of(node: Any, loc: tuple[int | str, ...]) -> int | None:
    """Follow a Pydantic error location into the YAML tree and return its 1-based line."""
    line: int | None = None
    current = node
    for part in loc:
        if isinstance(current, CommentedMap) and part in current:
            line = current.lc.key(part)[0] + 1
            current = current[part]
        elif isinstance(current, CommentedSeq) and isinstance(part, int) and part < len(current):
            line = current.lc.item(part)[0] + 1
            current = current[part]
        else:
            break
    if line is None and isinstance(node, CommentedMap):
        line = node.lc.line + 1
    return line


def load_model[M: BaseModel](path: Path, model: type[M]) -> tuple[M | None, list[Problem]]:
    data, problems = read_yaml(path)
    if problems:
        return None, problems
    if not isinstance(data, dict):
        return None, [
            Problem(file=str(path), line=1, message="expected a mapping at the top level")
        ]
    try:
        return model.model_validate(_plain(data)), []
    except ValidationError as exc:
        out: list[Problem] = []
        for err in exc.errors():
            loc = tuple(err["loc"])
            field = ".".join(str(p) for p in loc) or "(top level)"
            message = err["msg"].removeprefix("Value error, ")
            out.append(
                Problem(file=str(path), line=_line_of(data, loc), message=f"{field}: {message}")
            )
        return None, out


def line_in(path: Path, loc: tuple[int | str, ...]) -> int | None:
    """The line of a key path in a YAML file, for problems found after validation."""
    data, problems = read_yaml(path)
    return None if problems else _line_of(data, loc)


def _plain(value: Any) -> Any:
    """Convert ruamel's round-trip containers into plain dicts and lists for validation."""
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    return value
