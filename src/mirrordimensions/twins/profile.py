# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""Load a twin's profile, the single description of its inputs and outputs.

`locate`, `describe` and `exposed` are generated from it (build spec, "Systems").
"""

from __future__ import annotations

from functools import cache
from importlib.resources import files
from typing import Any

from ruamel.yaml import YAML

from mirrordimensions.network.payloads.behavior import Located, SurfaceTable


@cache
def load_profile(product: str) -> dict[str, Any]:
    text = files(f"mirrordimensions.twins.{product}").joinpath("profile.yaml").read_text("utf-8")
    data: dict[str, Any] = YAML(typ="safe").load(text)  # pyright: ignore[reportUnknownMemberType]
    return data


class Profile:
    def __init__(self, product: str) -> None:
        self.data = load_profile(product)
        self.table = SurfaceTable(self.data["surfaces"])

    @property
    def surfaces(self) -> list[dict[str, Any]]:
        return list(self.data["surfaces"])

    @property
    def errors(self) -> dict[str, Any]:
        return dict(self.data.get("errors", {}))

    @property
    def defaults(self) -> dict[str, Any]:
        return dict(self.data.get("defaults", {}))

    def locate(self, method: str, path: str) -> Located:
        return self.table.locate(method, path)

    def describe(self, method: str, path: str) -> str:
        return self.table.locate(method, path).sentence

    def exposed(self, method: str, path: str, body: bytes) -> list[str]:
        return self.table.exposed(method, path, body)
