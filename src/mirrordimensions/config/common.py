# SPDX-License-Identifier: Apache-2.0
"""Shared field types and helpers for the file formats."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints


class StrictModel(BaseModel):
    """Unknown keys are errors, so a typo in a file is reported, not ignored."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


Id = Annotated[
    str,
    StringConstraints(pattern=r"^[a-z][a-z0-9-]{0,62}$"),
]
"""Lowercase letters, digits and hyphens, starting with a letter."""

Hostname = Annotated[
    str,
    StringConstraints(
        pattern=r"^([A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?$",
        max_length=253,
        to_lower=True,
    ),
]

EnvName = Annotated[str, StringConstraints(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")]

OperationName = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9-]*\.[a-z][a-z0-9_]*$")]
"""A named operation or check registered by a twin adapter, e.g. `gitea.create_issue`."""


def duplicates_ignoring_case(values: Iterable[str]) -> list[str]:
    """Values that collide when case is ignored (macOS and Windows file systems ignore case)."""
    seen: dict[str, str] = {}
    dupes: list[str] = []
    for value in values:
        key = value.casefold()
        if key in seen:
            dupes.append(value)
        else:
            seen[key] = value
    return dupes
