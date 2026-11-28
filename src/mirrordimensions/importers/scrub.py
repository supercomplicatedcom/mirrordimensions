# SPDX-License-Identifier: Apache-2.0
"""What import never keeps: secrets and people (build spec, "Rules for handling real files").

`secret_like` is deliberately eager: a value it wrongly drops costs a fact, a value it wrongly
keeps could be a credential on disk.
"""

from __future__ import annotations

import math
import re
from typing import Any

SECRET_NAME = re.compile(
    r"(pass(word|wd|phrase)?|secret|token|api[_-]?key|access[_-]?key|private[_-]?key|"
    r"credential|auth|cookie|session|signature|salt|cert(ificate)?_?(key|pem)?|dsn|"
    r"connection[_-]?string|webhook)",
    re.IGNORECASE,
)
SECRET_VALUE = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\b(AKIA|ASIA)[0-9A-Z]{16}\b"),  # cloud access key ids
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),  # code host tokens
    re.compile(r"\bglpat-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b"),  # chat tokens
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),  # model provider keys
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),  # JWTs
    re.compile(r"://[^/\s:@]+:[^/\s@]+@"),  # credentials in a URL
)
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PEOPLE_FIELD = re.compile(
    r"(^|_)(user(name)?|login|email|e_mail|mail|owner_email|full_name|first_name|last_name|"
    r"display_name|given_name|family_name|member|members|assignee|author|committer|person|"
    r"phone|employee)s?($|_)",
    re.IGNORECASE,
)


def entropy(text: str) -> float:
    if not text:
        return 0.0
    counts = {c: text.count(c) for c in set(text)}
    return -sum(n / len(text) * math.log2(n / len(text)) for n in counts.values())


def secret_like(value: str, name: str = "") -> bool:
    """A value that is, or might be, a credential."""
    if name and SECRET_NAME.search(name):
        return True
    if any(p.search(value) for p in SECRET_VALUE):
        return True
    # A long unbroken run of random-looking characters: a key or token of some kind.
    for run in re.findall(r"[A-Za-z0-9+/=_-]{24,}", value):
        if entropy(run) > 4.0 and any(c.isdigit() for c in run) and any(c.isalpha() for c in run):
            return True
    return False


def person_like(value: str, name: str = "") -> bool:
    """A value that names or reaches a person."""
    return bool((name and PEOPLE_FIELD.search(name)) or EMAIL.search(value))


def strings(value: Any) -> list[str]:
    """Every string inside a value, however nested."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in strings(v)]  # pyright: ignore[reportUnknownVariableType]
    if isinstance(value, list):
        return [s for v in value for s in strings(v)]  # pyright: ignore[reportUnknownVariableType]
    return []
