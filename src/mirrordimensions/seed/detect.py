# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""What the seed folder must not pass on as it is (decision 0030, point 5).

Secrets are always dropped: a line holding one is left out whole, so nothing in the world
shows that something was removed. Personal data is found and listed with where it is, for
the user to confirm before the world is built; it is not changed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from mirrordimensions.importers.scrub import EMAIL, SECRET_VALUE, entropy

# `name = value` or `name: value` lines whose name says they hold a secret.
# The name may be part of a longer one (DB_PASSWORD, stripeSecretKey). Eager on purpose: a line
# wrongly left out costs a line of sample data, a line wrongly kept could be a credential.
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)[A-Za-z0-9_.-]*(pass(word|wd|phrase)?|secret|api[_-]?key|access[_-]?key|"
    r"private[_-]?key|client[_-]?secret|auth[_-]?token|token)[A-Za-z0-9_]*['\"]?\s*[:=]\s*"
    r"['\"]?[^\s'\"]{6,}"
)
_LONG_RANDOM = re.compile(r"[A-Za-z0-9+/=_-]{28,}")

PHONE = re.compile(
    r"(?<![\w.])(\+?\d{1,3}[ .-]?)?(\(\d{2,4}\)|\d{2,4})[ .-]\d{3,4}[ .-]\d{3,4}(?!\w|\.\d)"
)
CARD = re.compile(r"(?<!\d)(\d[ -]?){12,18}\d(?!\d)")
US_SSN = re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")
UK_NINO = re.compile(r"\b[A-CEGHJ-PR-TW-Z]{2} ?\d{2} ?\d{2} ?\d{2} ?[A-D]\b")
STREET = re.compile(
    r"\b\d{1,5} [A-Z][a-z]+(?: [A-Z][a-z]+)* (Street|St|Avenue|Ave|Road|Rd|Lane|Ln|Drive|Dr|"
    r"Boulevard|Blvd|Way|Court|Ct|Place|Pl)\b"
)


@dataclass(frozen=True)
class Personal:
    path: str
    line: int
    kind: str  # "email address", "phone number", "card number", "national id", "street address"
    shown: str  # the value with most of it hidden, for the review


def secret_on(line: str) -> bool:
    """Whether a line holds what looks like a credential."""
    if any(p.search(line) for p in SECRET_VALUE) or _SECRET_ASSIGNMENT.search(line):
        return True
    return any(
        entropy(run) > 4.2 and any(c.isdigit() for c in run) and any(c.isalpha() for c in run)
        for run in _LONG_RANDOM.findall(line)
    )


def without_secrets(path: str, text: str) -> tuple[str, int]:
    """The text with every line holding a secret left out, and how many were."""
    kept: list[str] = []
    dropped = 0
    for line in text.split("\n"):
        if secret_on(line):
            dropped += 1
        else:
            kept.append(line)
    return "\n".join(kept), dropped


def _luhn(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2 == 1:
            n = n * 2 - 9 if n > 4 else n * 2
        total += n
    return total % 10 == 0


def _hide(value: str) -> str:
    return value[:2] + "…" + value[-2:] if len(value) > 6 else "…"


def personal_in(path: str, text: str, company_domain: str) -> list[Personal]:
    """Personal data in a text, by line: for the user to confirm, never silently kept."""
    found: list[Personal] = []
    domain = company_domain.lower()
    for number, line in enumerate(text.split("\n"), start=1):
        for m in EMAIL.finditer(line):
            address = m.group(0).lower()
            if not (address.endswith("@" + domain) or address.endswith("." + domain)):
                found.append(Personal(path, number, "email address", _hide(address)))
        cards: list[tuple[int, int]] = []
        for m in CARD.finditer(line):
            digits = re.sub(r"\D", "", m.group(0))
            if 13 <= len(digits) <= 19 and _luhn(digits):
                found.append(Personal(path, number, "card number", "…" + digits[-4:]))
                cards.append(m.span())
        for m in US_SSN.finditer(line):
            found.append(Personal(path, number, "national id", "…" + m.group(0)[-4:]))
        for m in UK_NINO.finditer(line):
            found.append(Personal(path, number, "national id", _hide(m.group(0))))
        for m in PHONE.finditer(line):
            digits = re.sub(r"\D", "", m.group(0))
            inside_card = any(a <= m.start() and m.end() <= b for a, b in cards)
            if 9 <= len(digits) <= 15 and not inside_card:
                found.append(Personal(path, number, "phone number", "…" + digits[-3:]))
        for m in STREET.finditer(line):
            found.append(Personal(path, number, "street address", _hide(m.group(0))))
    return found
