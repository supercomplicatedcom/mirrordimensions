# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""Load a twin's profile, the single description of its inputs and outputs.

`locate`, `describe` and `exposed` are generated from it (build spec, "Systems").
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from importlib.resources import files
from typing import Any

from ruamel.yaml import YAML

from mirrordimensions.network.payloads.behavior import Located, SurfaceTable


@cache
def load_profile(product: str) -> dict[str, Any]:
    package = f"mirrordimensions.twins.{product.replace('-', '_')}"  # device-platform
    text = files(package).joinpath("profile.yaml").read_text("utf-8")
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

    def locate(
        self, method: str, path: str, body: bytes = b"", names: dict[str, str] | None = None
    ) -> Located:
        return self.table.locate(method, path, body, names)

    def describe(self, method: str, path: str, body: bytes = b"") -> str:
        return self.table.locate(method, path, body).sentence

    def exposed(self, method: str, path: str, body: bytes) -> list[str]:
        return self.table.exposed(method, path, body)


@cache
def profile_of(product: str) -> Profile:
    return Profile(product)


@dataclass(frozen=True)
class ResourceRef:
    """Where a request acted: a surface of the system and, where it names one, a resource."""

    surface: str
    resource: str | None
    access: str | None


def _exchange(exchange: dict[str, Any]) -> tuple[str, str, bytes, dict[str, str] | None]:
    body = exchange.get("req_body", b"")
    return (
        str(exchange.get("method", "GET")),
        str(exchange.get("path", "")),
        body.encode() if isinstance(body, str) else bytes(body or b""),
        exchange.get("names"),
    )


class ProfileMethods:
    """`locate`, `describe` and `exposed` for a twin adapter, generated from its profile.

    An exchange is an `http.exchange` event's data (`method`, `path`), with the request body
    as `req_body` and the names learned so far in the run as `names`, when known."""

    product: str

    def profile(self) -> Profile:
        return profile_of(self.product)

    def locate(self, exchange: dict[str, Any]) -> ResourceRef | None:
        method, path, body, names = _exchange(exchange)
        found = self.profile().locate(method, path, body, names)
        if found.surface == "unknown":
            return None
        return ResourceRef(surface=found.surface, resource=found.resource, access=found.access)

    def describe(self, exchange: dict[str, Any]) -> str:
        method, path, body, names = _exchange(exchange)
        return self.profile().locate(method, path, body, names).sentence

    def exposed(self, exchange: dict[str, Any], response: bytes) -> list[str]:
        method, path, _, _ = _exchange(exchange)
        return self.profile().exposed(method, path, response)
