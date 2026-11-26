# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""Enforce two boundaries in `src/mirrordimensions/`.

1. Every import is the standard library, this package, or a declared runtime dependency.
   Nothing may import cloud-service code or any undeclared package.
2. Only `hostos/` and `engine/` may ask which OS they run on (`sys.platform`, `os.name`,
   the `platform` module, or OS-only modules such as `msvcrt`, `fcntl`, `winreg`).
3. Only `twins/` may import a product by name (`mirrordimensions.twins.<product>`); everything
   else goes through the twin interface in `twins/base.py`.

Exit 0 when clean, 1 with one line per violation otherwise.
"""

from __future__ import annotations

import ast
import re
import sys
import tomllib
from importlib.metadata import packages_distributions
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = "mirrordimensions"
OS_ALLOWED = ("hostos", "engine")
TWIN_SHARED = {"base", "relay", "profile"}
OS_MODULES = {"platform", "msvcrt", "fcntl", "winreg", "_winapi", "posix", "nt"}


def declared_distributions(pyproject: Path) -> set[str]:
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    names: set[str] = set()
    for req in data["project"]["dependencies"]:
        match = re.match(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)", req)
        if match:
            names.add(normalize(match.group(1)))
    return names


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def imports_of(tree: ast.AST) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [(node.lineno, alias.name) for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.append((node.lineno, node.module))
    return found


def os_checks(tree: ast.AST) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            pair = (node.value.id, node.attr)
            if pair in {("sys", "platform"), ("os", "name"), ("sys", "getwindowsversion")}:
                found.append((node.lineno, f"{pair[0]}.{pair[1]}"))
    return found


# Files that run alone inside the world beside nothing but each other (decision 0026).
IN_WORLD = {
    ("devices", "world", "sim.py"),
    ("devices", "world", "mqttwire.py"),
    ("devices", "world", "bus.py"),
    ("twins", "device_platform", "server.py"),
}
SIBLINGS = {"sim", "mqttwire"}  # the files copied beside them in their container


def violations(src: Path, allowed_dists: set[str]) -> list[str]:
    stdlib = set(sys.stdlib_module_names)
    module_to_dists = packages_distributions()
    out: list[str] = []
    for path in sorted(src.rglob("*.py")):
        rel = path.relative_to(src)
        if "payloads" in rel.parts:
            continue  # files copied into engine containers; never imported on the host
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        in_os_area = rel.parts[0] in OS_ALLOWED
        for line, module in imports_of(tree):
            top = module.split(".")[0]
            where = f"{PACKAGE}/{rel.as_posix()}:{line}"
            if top in OS_MODULES and not in_os_area:
                out.append(f"{where}: imports {top}; only hostos/ and engine/ may check the OS")
            parts = module.split(".")
            if (
                rel.parts[0] != "twins"
                and parts[:2] == [PACKAGE, "twins"]
                and len(parts) > 2
                and parts[2] not in TWIN_SHARED
            ):
                out.append(f"{where}: imports the product {parts[2]!r}; use the twin interface")
            if (
                rel.parts[:2] == ("mcp", "world")
                and parts[:1] == [PACKAGE]
                and (parts[1:2] == ["service"] or parts[1:3] == ["mcp", "operator"])
            ):
                out.append(f"{where}: the world MCP server may not import {module} (decision 0009)")
            if rel.parts[:3] == ("mcp", "world", "front.py") and top == PACKAGE:
                out.append(f"{where}: front.py runs alone inside the world; standard library only")
            if rel.parts in IN_WORLD:
                if top in SIBLINGS or module in {f"{PACKAGE}.devices.world.{n}" for n in SIBLINGS}:
                    continue  # a sibling: the package on the host, the file beside it inside
                if top == PACKAGE and module != f"{PACKAGE}.devices.world":
                    out.append(f"{where}: runs inside the world; standard library only (0026)")
            if top == PACKAGE or top in stdlib or top == "__future__":
                continue
            dists = {normalize(d) for d in module_to_dists.get(top, [])}
            if not dists & allowed_dists:
                out.append(
                    f"{where}: imports {top!r}, which is not a declared dependency of {PACKAGE}"
                )
        if not in_os_area:
            for line, expr in os_checks(tree):
                where = f"{PACKAGE}/{rel.as_posix()}:{line}"
                out.append(f"{where}: uses {expr}; only hostos/ and engine/ may check the OS")
    return out


def main() -> int:
    problems = violations(ROOT / "src" / PACKAGE, declared_distributions(ROOT / "pyproject.toml"))
    for problem in problems:
        print(problem)
    if problems:
        print(f"{len(problems)} import boundary violation(s)")
        return 1
    print("ok    imports stay within the standard library and declared dependencies")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
