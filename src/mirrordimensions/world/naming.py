# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""What a world calls its core repositories and channels, for scenarios and agent files.

Each world names its core repositories and channels its own way (decision 0029, point 4).
Scenarios and agent files written with the usual names (`billing-service`, `incidents`) are
translated to the world's, and scenarios can name a role directly: `{{ repo.billing }}`,
`{{ channel.incidents }}`. Translation happens on the host, before anything reaches a twin.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from mirrordimensions.world.model import World
from mirrordimensions.world.profile import CORE_ROLES

# Keys whose values name chat channels. Channel names are ordinary words ("incidents"), so
# they are translated only where a channel is meant, and after a `#` in text.
CHANNEL_KEYS = frozenset({"channel", "channels", "outside", "in"})


def repos(world: World) -> dict[str, str]:
    return {k.removeprefix("repo:"): v for k, v in world.names.items() if k.startswith("repo:")}


def channels(world: World) -> dict[str, str]:
    return {
        k.removeprefix("channel:"): v for k, v in world.names.items() if k.startswith("channel:")
    }


def template_values(world: World) -> dict[str, str]:
    """`repo.<role>` and `channel.<name>` for scenario templates."""
    values = {f"repo.{CORE_ROLES[k]}": v for k, v in repos(world).items() if k in CORE_ROLES}
    values |= {f"repo.{k}": v for k, v in repos(world).items()}
    values |= {f"channel.{k}": v for k, v in channels(world).items()}
    return values


class Translator:
    def __init__(self, world: World) -> None:
        self.repos = {k: v for k, v in repos(world).items() if k != v}
        self.channels = {k: v for k, v in channels(world).items() if k != v}
        self._repo = (
            re.compile(
                r"(?<![A-Za-z0-9-])(" + "|".join(map(re.escape, self.repos)) + r")(?![A-Za-z0-9-])"
            )
            if self.repos
            else None
        )
        self._hash = (
            re.compile(r"#(" + "|".join(map(re.escape, self.channels)) + r")(?![A-Za-z0-9-])")
            if self.channels
            else None
        )

    def text(self, value: str) -> str:
        if self._repo:
            value = self._repo.sub(lambda m: self.repos[m.group(1)], value)
        if self._hash:
            value = self._hash.sub(lambda m: "#" + self.channels[m.group(1)], value)
        return value

    def channel(self, value: str) -> str:
        return self.channels.get(value, value)

    def value(self, value: Any, key: str = "") -> Any:
        """A scenario's data with the world's names, recursively."""
        if isinstance(value, Mapping):
            items: dict[Any, Any] = dict(value)  # pyright: ignore[reportUnknownArgumentType]
            return {
                (self.text(k) if isinstance(k, str) else k): self.value(v, f"{k}")
                for k, v in items.items()
            }
        if isinstance(value, list):
            return [self.value(v, key) for v in value]  # pyright: ignore[reportUnknownVariableType]
        if isinstance(value, str):
            if key in CHANNEL_KEYS:
                return self.channel(value)
            return self.text(value)
        return value

    def grants(self, grants: Mapping[str, Any]) -> dict[str, Any]:
        """An agent file's grants for one system, with the world's names."""
        out = dict(grants)
        if isinstance(out.get("repos"), Mapping):
            out["repos"] = {self.repos.get(k, k): v for k, v in out["repos"].items()}
        if isinstance(out.get("channels"), list):
            out["channels"] = [self.channel(c) for c in out["channels"]]
        return out
