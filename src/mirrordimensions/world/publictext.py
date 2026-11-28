# SPDX-License-Identifier: Apache-2.0
"""How much of what an agent can read in a world is in the public package, word for word.

The project is open source and models may be trained on it, so a world whose text is in the
repository can be recognised. Every text the agent can read is compared with the text of the
installed package: a text counts as public when it holds a run of `RUN` or more words found
there (decision 0029). The comparison is offline; nothing is sent anywhere.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from functools import cache
from pathlib import Path

from pydantic import BaseModel, Field

from mirrordimensions.world.model import World

RUN = 8
LIMIT = 0.02  # the share of texts allowed to hold a public run (decision 0029)

_WORD = re.compile(r"[a-z0-9']+")
_SUFFIXES = frozenset({".py", ".yaml", ".yml", ".md", ".json", ".txt", ".toml", ".html", ".csv"})
_SKIP = ("portal/static", "portal/web", "__pycache__")

KINDS = ("issue", "comment", "commit", "chat", "direct", "file")


class KindCount(BaseModel):
    kind: str
    public: int
    total: int


class PublicTextReport(BaseModel):
    run: int = RUN
    limit: float = LIMIT
    public: int = Field(description="Texts holding a run found in the package")
    total: int
    kinds: list[KindCount]

    @property
    def share(self) -> float:
        return self.public / self.total if self.total else 0.0

    @property
    def within_limit(self) -> bool:
        return self.share <= self.limit

    def line(self) -> str:
        parts = ", ".join(f"{k.kind} {k.public}/{k.total}" for k in self.kinds if k.total)
        return (
            f"Public text: {self.public} of {self.total} texts ({self.share:.0%}) share a run of "
            f"{self.run} words with the published package; the limit is {self.limit:.0%} "
            f"(decision 0029). By kind: {parts}"
        )


def words(text: str) -> list[str]:
    return _WORD.findall(text.lower())


def _grams(tokens: list[str], n: int) -> Iterator[int]:
    for i in range(len(tokens) - n + 1):
        yield hash(" ".join(tokens[i : i + n]))


def package_root() -> Path:
    return Path(__file__).resolve().parent.parent


def corpus_files(root: Path) -> list[Path]:
    return sorted(
        p
        for p in root.rglob("*")
        if p.suffix in _SUFFIXES
        and p.is_file()
        and not any(skip in p.relative_to(root).as_posix() for skip in _SKIP)
    )


def gram_set(texts: Iterable[str], n: int = RUN) -> frozenset[int]:
    found: set[int] = set()
    for text in texts:
        found.update(_grams(words(text), n))
    return frozenset(found)


@cache
def package_grams(root: Path | None = None, n: int = RUN) -> frozenset[int]:
    folder = root or package_root()
    return gram_set((_readable(p) for p in corpus_files(folder)), n)


def _readable(path: Path) -> str:
    """A file as its words run: in YAML, comment-only lines are dropped, so a comment placed
    between two lines cannot hide that they run on in the file (decision 0029)."""
    text = path.read_text(encoding="utf-8", errors="ignore")
    if path.suffix in (".yaml", ".yml"):
        text = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    return text


def agent_texts(world: World) -> Iterator[tuple[str, str]]:
    """(kind, text) for every text the agent can read in the world's systems."""
    for repo in world.repositories:
        for issue in repo.issues:
            yield "issue", f"{issue.title}. {issue.body}"
            for comment in issue.comments:
                yield "comment", comment.body
        latest: dict[str, str] = {}
        for commit in repo.commits:
            yield "commit", commit.message
            for path, text in commit.files.items():
                if text is None:
                    latest.pop(path, None)
                else:
                    latest[path] = text
        for text in latest.values():
            yield "file", text
    for channel in world.channels:
        for message in channel.messages:
            yield "chat", message.text
    for thread in world.direct:
        for message in thread.messages:
            yield "direct", message.text


def check(
    world: World,
    grams: frozenset[int] | None = None,
    n: int = RUN,
    skip: frozenset[str] = frozenset(),
) -> PublicTextReport:
    """`skip`: texts the user supplied (a seed folder's), which are not the package's."""
    public_grams = package_grams(None, n) if grams is None else grams
    counts = {kind: [0, 0] for kind in KINDS}
    for kind, text in agent_texts(world):
        if text in skip:
            continue
        tokens = words(text)
        if len(tokens) < n:
            continue
        counts[kind][1] += 1
        if any(g in public_grams for g in _grams(tokens, n)):
            counts[kind][0] += 1
    kinds = [KindCount(kind=k, public=v[0], total=v[1]) for k, v in counts.items()]
    return PublicTextReport(
        run=n,
        public=sum(k.public for k in kinds),
        total=sum(k.total for k in kinds),
        kinds=kinds,
    )
