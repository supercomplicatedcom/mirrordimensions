# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""World import (build spec, "World import"; decision 0025).

Each importer reads one kind of file on the host, in place, and returns facts: one statement
each, with its evidence. Importers know nothing of each other; `service.imports` merges their
facts into one draft for review. Secrets and people never become facts: values marked
sensitive or matching secret patterns are dropped and counted, and names, emails and user
identifiers are not read.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

FactKind = Literal[
    "system", "hostname", "endpoint", "tool", "resource", "group", "assignment", "link"
]
Confidence = Literal["stated", "derived", "guessed"]


class SourceRef(BaseModel):
    importer: str
    file: str = Field(
        description="The file's name only: where it lives on this computer is not kept"
    )
    location: str = Field(default="", description="Where in the file, e.g. mcpServers.eng-tools")


class Fact(BaseModel):
    id: str
    kind: FactKind
    subject: str  # what the fact is about, e.g. "code-hosting" or "mcp:eng-tools"
    value: dict[str, Any]
    source: SourceRef
    confidence: Confidence = "stated"


class ImportResult(BaseModel):
    importer: str
    file: str
    facts: list[Fact] = Field(default_factory=list[Fact])
    summary: str = ""  # one line for the review's "what was read"
    skipped_secrets: int = 0
    skipped_people: int = 0
    skipped: dict[str, int] = Field(default_factory=dict[str, int])  # other things left out


class Importer(Protocol):
    name: str
    label: str  # for people: "Agent tool configuration"

    def detect(self, path: Path, data: Any) -> bool: ...
    def read(self, path: Path, data: Any) -> ImportResult: ...


def builtin() -> list[Importer]:
    from mirrordimensions.importers import mcp_config, mcp_tools, openapi, terraform

    return [mcp_config.McpConfig(), mcp_tools.McpTools(), openapi.OpenApi(), terraform.Terraform()]


def available() -> list[Importer]:
    """The built-in importers, then any a plug-in registers (entry point group
    `mirrordimensions.importers`)."""
    from mirrordimensions.plugins import discover, load

    found = builtin()
    names = {i.name for i in found}
    for ref in discover():
        if ref.group == "importer" and ref.name not in names:
            made = load("importer", ref.name)
            found.append(made() if isinstance(made, type) else made)
    return found
