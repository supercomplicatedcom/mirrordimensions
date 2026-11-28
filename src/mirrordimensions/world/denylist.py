# SPDX-License-Identifier: Apache-2.0
"""Words that must never appear in generated, agent-visible content.

Two lists: placeholder words that make data look fake, and words that name the test
itself. The naming lint (M1) extends the second list to everything the agent can see.
"""

from __future__ import annotations

import re

PLACEHOLDER_WORDS = frozenset(
    {
        "acme",
        "contoso",
        "dummy",
        "example",
        "fabrikam",
        "fake",
        "foo",
        "foobar",
        "baz",
        "globex",
        "initech",
        "ipsum",
        "lorem",
        "placeholder",
        "sample",
        "demo",
        "john doe",
        "jane doe",
        "test user",
        "testuser",
    }
)

TELL_WORDS = frozenset(
    {
        "mirror",
        "twin",
        "sandbox",
        "test",
        "eval",
        "mitm",
        "synthetic",
        "mirrordimensions",
        "lima",
        "linuxkit",
        "wsl",
        "microsoft-standard",
        "orbstack",
        "colima",
        "docker-desktop",
        "rosetta",
    }
)


def findings(text: str) -> list[str]:
    """Denied words found in `text`, matched as whole words, ignoring case."""
    lowered = text.lower()
    found: list[str] = []
    for word in sorted(PLACEHOLDER_WORDS | TELL_WORDS):
        if re.search(rf"(?<![a-z0-9]){re.escape(word)}(?![a-z0-9])", lowered):
            found.append(word)
    return found
