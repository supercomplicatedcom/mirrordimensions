# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""Contracts for the plug-in groups other than engines.

They are deliberately small now and grow with the milestones that use them: twin
adapters in M2, run storage and sinks in M5, importers in M8, authentication in M7.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from typing import Any, Protocol

from mirrordimensions.config.events import Event
from mirrordimensions.config.result import Result


class RunStore(Protocol):
    """Where run artifacts live (`mirrordimensions.run_stores`). Default: files on disk."""

    name: str

    def write_events(self, run_id: str, events: Iterable[Event]) -> None: ...
    def read_events(self, run_id: str) -> Iterator[Event]: ...
    def write_result(self, result: Result) -> None: ...
    def read_result(self, run_id: str) -> Result: ...
    def list_runs(self) -> list[str]: ...


class Authenticator(Protocol):
    """Who may use the portal and the operator MCP server (`mirrordimensions.authenticators`)."""

    name: str

    def authenticate(self, headers: dict[str, str]) -> str | None:
        """Return the user's identifier, or None to refuse."""
        ...


class EventSink(Protocol):
    """Somewhere events are sent as a run produces them (`mirrordimensions.sinks`)."""

    name: str

    def emit(self, event: Event) -> None: ...
    def close(self) -> None: ...


class TwinAdapter(Protocol):
    """A product behind an adapter (`mirrordimensions.twins`). Filled in during M2."""

    product: str

    def operations(self) -> dict[str, Callable[..., Any]]: ...
    def checks(self) -> dict[str, Callable[..., Any]]: ...
    def dump_state(self) -> dict[str, Any]: ...


class Importer(Protocol):
    """Reads one kind of description file into facts (`mirrordimensions.importers`). M8."""

    name: str

    def detect(self, path: Path) -> bool: ...
    def read(self, path: Path) -> Any: ...


CheckFunction = Callable[..., Any]
"""A named check (`mirrordimensions.checks`), e.g. `gitea.file_not_contains`."""
