# SPDX-License-Identifier: Apache-2.0
"""Minimal plug-ins for tests."""

from __future__ import annotations

from typing import Any


class MemoryRunStore:
    name = "memory"

    def __init__(self) -> None:
        self.events: dict[str, list[Any]] = {}


class CollectSink:
    name = "collect"

    def __init__(self) -> None:
        self.events: list[Any] = []

    def emit(self, event: Any) -> None:
        self.events.append(event)

    def close(self) -> None:
        pass
