# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""Text composed from short parts and the world's own facts (decision 0029).

A profile ships no whole sentences. It ships templates whose literal runs are short, with
slots filled from the profile's vocabulary and the world, so the texts an agent reads are
made for this world and are not in the package word for word.

Template syntax:

- `{name}`: a value bound for this text (`let`), a profile symbol, or a world fact. Symbols
  are lists; one entry is chosen, and it may hold slots of its own.
- `{name|cap}` and `{name|lower}`: the value with its first letter raised or lowered.
- `{3-40}`: a whole number in the range.
- `{a/b/c}`: one of the words or short phrases given.

Literal text between slots is kept to `MAX_LITERAL` words, which `literal_runs` checks.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator, Mapping, Sequence

from mirrordimensions.errors import MirrorError
from mirrordimensions.world.rng import Rng

MAX_LITERAL = 6
_SLOT = re.compile(r"\{([^{}]+)\}")
_RANGE = re.compile(r"^(\d+)-(\d+)$")
_DEPTH = 12

Alternatives = str | Sequence[str]
Facts = Callable[[str], str | None]


def _no_facts(_name: str) -> str | None:
    return None


class Composer:
    """Renders templates with a seeded source, the profile's symbols and the world's facts."""

    def __init__(
        self,
        rng: Rng,
        symbols: Mapping[str, Sequence[str]],
        facts: Facts = _no_facts,
    ) -> None:
        self.rng = rng
        self.symbols = symbols
        self.facts = facts

    def pick(self, alternatives: Alternatives) -> str:
        if isinstance(alternatives, str):
            return alternatives
        return self.rng.choice(alternatives)

    def bind(
        self, let: Mapping[str, Alternatives], bound: Mapping[str, str] | None = None
    ) -> dict[str, str]:
        """Values chosen once for a text and everything said about it, in order."""
        values = dict(bound or {})
        for name, alternatives in let.items():
            values[name] = _spaces(self._expand(self.pick(alternatives), values, 0))
        return values

    def render(
        self,
        alternatives: Alternatives,
        bound: Mapping[str, str] | None = None,
        capital: bool = True,
    ) -> str:
        """One text. `capital` raises its first letter, as issues and documents are written;
        chat passes False and keeps what the template wrote."""
        text = _spaces(self._expand(self.pick(alternatives), bound or {}, 0))
        if not capital:
            return text
        text = re.sub(r"(^|[.!?] )(\S+)", lambda m: m.group(1) + _raise(m.group(2)), text)
        return text

    def _expand(self, template: str, bound: Mapping[str, str], depth: int) -> str:
        if depth > _DEPTH:
            raise MirrorError(
                "A profile's templates refer to each other without end.",
                f"Gave up expanding: {template[:80]!r}",
                "Check the profile's symbols for one that names itself.",
            )
        return _SLOT.sub(lambda m: self._slot(m.group(1), bound, depth), template)

    def _slot(self, body: str, bound: Mapping[str, str], depth: int) -> str:
        if "/" in body and "|" not in body:
            return self._expand(self.rng.choice(body.split("/")), bound, depth + 1)
        if found := _RANGE.match(body):
            return str(self.rng.randint(int(found.group(1)), int(found.group(2))))
        name, _, modifier = body.partition("|")
        value = self._value(name.strip(), bound, depth)
        if modifier == "cap":
            return value[:1].upper() + value[1:]
        if modifier == "lower":
            return value[:1].lower() + value[1:]
        return value

    def _value(self, name: str, bound: Mapping[str, str], depth: int) -> str:
        if name in bound:
            return bound[name]
        if name in self.symbols:
            return self._expand(self.rng.choice(self.symbols[name]), bound, depth + 1)
        fact = self.facts(name)
        if fact is not None:
            return fact
        raise MirrorError(
            "A profile's template names something that does not exist.",
            f"Nothing is called {{{name}}}: it is not bound, not a symbol and not a world fact.",
            "Add it to the profile's symbols, or correct the name.",
        )


def _raise(word: str) -> str:
    """A sentence's first word with a capital, unless it is a path, file or identifier
    (`pipeline/load.py`, `sync_users.sh`, `billing-service#41`), which keep their case."""
    if re.search(r"[/_#]|\.[a-z]", word.rstrip(".,:;!?")):
        return word
    return word[:1].upper() + word[1:]


def _spaces(text: str) -> str:
    """One space between words, none before punctuation; an emoji code such as `:tada:`
    keeps the space before it."""
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" ([,.;!?])", r"\1", text)
    return re.sub(r" :(?![a-z0-9_+-]+:)", ":", text).strip()


def slots(template: str) -> Iterator[str]:
    """The names a template refers to (not ranges or inline choices)."""
    for found in _SLOT.finditer(template):
        body = found.group(1)
        if "/" in body and "|" not in body:
            for part in body.split("/"):
                yield from slots(part)
            continue
        if _RANGE.match(body):
            continue
        yield body.partition("|")[0].strip()


def literal_runs(template: str) -> Iterator[str]:
    """The literal stretches of a template, between its slots."""
    for part in _SLOT.split(template)[::2]:
        if part.strip():
            yield part.strip()


def _words(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9']+", text))


def longest_literal(template: str) -> int:
    """The longest run of words a rendered text can share with the profile's own file. An
    inline choice reads as plain words there: its first option runs on from the text before
    it, and its last option into the text after it."""
    longest = run = 0
    for i, part in enumerate(_SLOT.split(template)):
        if i % 2 == 0:
            run += _words(part)
        elif "/" in part and "|" not in part and "{" not in part:
            options = [_words(o) for o in part.split("/")]
            longest = max(longest, run + options[0], *options)
            run = options[-1]
        else:
            run = 0
        longest = max(longest, run)
    return longest
