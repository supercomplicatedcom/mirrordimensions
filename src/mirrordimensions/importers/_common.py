# SPDX-License-Identifier: Apache-2.0
"""Helpers every importer uses: stable fact ids, product names through the catalog, and
host names from URLs."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any
from urllib.parse import urlsplit

from mirrordimensions.catalog.index import Entry, resolve
from mirrordimensions.importers import Confidence, Fact, FactKind, SourceRef
from mirrordimensions.world.names import slug


def fact(
    importer: str,
    file: str,
    location: str,
    kind: FactKind,
    subject: str,
    value: dict[str, Any],
    confidence: Confidence = "stated",
) -> Fact:
    digest = hashlib.sha256(
        json.dumps([importer, file, location, kind, subject, value], sort_keys=True).encode()
    ).hexdigest()[:10]
    return Fact(
        id=f"f_{digest}",
        kind=kind,
        subject=subject,
        value=value,
        source=SourceRef(importer=importer, file=file, location=location),
        confidence=confidence,
    )


_PACKAGING = re.compile(
    r"(^@[\w.-]+/|^mcp[-_]server[-_]|^mcp[-_]|[-_]mcp[-_]server$|[-_]mcp$|[-_]server$|[-_]api$)"
)


def product(name: str) -> Entry | None:
    """The catalog entry a product name, package or command names, if any: `gitea-mcp`,
    `@acme/mcp-server-gitea` and `Gitea API` all resolve to Gitea."""
    text = (
        name.strip().rsplit("/", 1)[-1]
        if "/" in name and not name.startswith("@")
        else name.strip()
    )
    for candidate in (text, re.sub(r"\s+api$", "", text, flags=re.IGNORECASE)):
        found = resolve(candidate)
        if found is not None:
            return found
        stripped = candidate
        for _ in range(3):
            stripped = _PACKAGING.sub("", stripped)
        if stripped and stripped != candidate:
            found = resolve(stripped)
            if found is not None:
                return found
    return None


def subject_for(entry: Entry | None, name: str) -> str:
    """Facts about one product share a subject: its catalog slug, or the name as a slug."""
    return entry.slug if entry is not None else slug(name)


def host_of(url: str) -> tuple[str, str] | None:
    """(hostname, path) for an absolute http(s) URL with a literal host; None for a relative
    URL or one whose host is still a variable."""
    if "${" in url or "{" in url.split("//", 1)[-1].split("/", 1)[0]:
        return None
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname or "." not in parts.hostname:
        return None
    return parts.hostname.lower().rstrip("."), parts.path or "/"


def load_document(path: Any) -> Any:
    """JSON, or YAML for the formats written in it; None when it is neither."""
    from pathlib import Path

    text = Path(path).read_text(encoding="utf-8")
    try:
        return json.loads(text)
    except ValueError:
        pass
    from ruamel.yaml import YAML

    try:
        return YAML(typ="safe").load(text)  # pyright: ignore[reportUnknownMemberType]
    except Exception:  # noqa: BLE001 - any YAML error: not a document this reads
        return None
