# SPDX-License-Identifier: Apache-2.0
"""A deterministic random source: the same seed and label give the same sequence on every
host and Python version (random.Random makes no such promise across releases)."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence


class Rng:
    def __init__(self, seed: int, label: str) -> None:
        self._key = f"{seed}:{label}".encode()
        self._n = 0

    def _next(self) -> int:
        self._n += 1
        return int.from_bytes(
            hashlib.sha256(self._key + b":" + str(self._n).encode()).digest()[:8], "big"
        )

    def random(self) -> float:
        return self._next() / 2**64

    def randint(self, low: int, high: int) -> int:
        return low + self._next() % (high - low + 1)

    def choice[T](self, items: Sequence[T]) -> T:
        return items[self._next() % len(items)]

    def chance(self, p: float) -> bool:
        return self.random() < p

    def sample[T](self, items: Sequence[T], k: int) -> list[T]:
        pool = list(items)
        out: list[T] = []
        for _ in range(min(k, len(pool))):
            out.append(pool.pop(self._next() % len(pool)))
        return out

    def shuffled[T](self, items: Sequence[T]) -> list[T]:
        return self.sample(items, len(items))

    def child(self, label: str) -> Rng:
        return Rng(
            int.from_bytes(self._key[:8].ljust(8, b"\0"), "big"), f"{self._key.decode()}/{label}"
        )
