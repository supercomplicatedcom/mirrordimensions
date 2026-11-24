# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""Errors that reach the user. Every one says what failed, why, and what to do next."""

from __future__ import annotations


class MirrorError(Exception):
    """An actionable error. The CLI prints it in three parts and exits with `exit_code`."""

    exit_code = 2

    def __init__(self, what: str, why: str, fix: str) -> None:
        super().__init__(what)
        self.what = what
        self.why = why
        self.fix = fix

    def lines(self) -> list[str]:
        return [self.what, self.why, self.fix]

    def __str__(self) -> str:
        return " ".join(self.lines())


class NotAProjectError(MirrorError):
    def __init__(self, start: str) -> None:
        super().__init__(
            "No project here.",
            f"No mirror.yaml was found in {start} or any folder above it.",
            "Run: mirror init <dir>, or pass --project <path>.",
        )


class LockHeldError(MirrorError):
    def __init__(self, holder: str) -> None:
        super().__init__(
            "Another operation is in progress.",
            f"It is held by {holder}.",
            "Wait for it to finish, then try again.",
        )
