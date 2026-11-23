# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""Seeded choices that are identical on every host and Python version.

`random.Random` is not guaranteed to give the same sequence across Python releases, so
choices are derived from SHA-256 of the seed and a label instead.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence


def number(seed: int, label: str) -> int:
    digest = hashlib.sha256(f"{seed}:{label}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


def pick[T](seed: int, label: str, items: Sequence[T]) -> T:
    if not items:
        raise ValueError("nothing to pick from")
    return items[number(seed, label) % len(items)]


def between(seed: int, label: str, low: int, high: int) -> int:
    """An integer in [low, high]."""
    return low + number(seed, label) % (high - low + 1)
