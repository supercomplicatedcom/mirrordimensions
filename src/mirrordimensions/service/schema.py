# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from typing import Any

from mirrordimensions.config import SCHEMAS
from mirrordimensions.errors import MirrorError


def json_schema(kind: str | None = None) -> dict[str, Any]:
    """JSON Schema for one file format, or all of them keyed by name."""
    if kind is None:
        return {name: model.model_json_schema() for name, model in SCHEMAS.items()}
    if kind not in SCHEMAS:
        raise MirrorError(
            f"Unknown schema {kind!r}.",
            f"Known schemas: {', '.join(SCHEMAS)}.",
            "Run: mirror schema <name>, or mirror schema for all of them.",
        )
    return SCHEMAS[kind].model_json_schema()
