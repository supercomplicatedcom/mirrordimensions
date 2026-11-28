# SPDX-License-Identifier: Apache-2.0
"""Locate a project directory: the folder holding `mirror.yaml`."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from mirrordimensions.errors import NotAProjectError

MANIFEST = "mirror.yaml"
STATE_DIR = ".mirror"


class Project(BaseModel):
    root: Path

    @property
    def manifest_path(self) -> Path:
        return self.root / MANIFEST

    @property
    def state_dir(self) -> Path:
        return self.root / STATE_DIR

    @property
    def agents_dir(self) -> Path:
        return self.root / "agents"

    @property
    def scenarios_dir(self) -> Path:
        return self.root / "scenarios"


def find_project(start: Path) -> Project:
    """The nearest folder at or above `start` that holds a manifest."""
    start = start.resolve()
    for folder in (start, *start.parents):
        if (folder / MANIFEST).is_file():
            return Project(root=folder)
    raise NotAProjectError(str(start))
