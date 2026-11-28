# SPDX-License-Identifier: Apache-2.0
"""Output rules from the build spec.

- One line per step, prefixed `ok` or `FAIL` in a fixed-width column.
- Color only as an enhancement; `NO_COLOR` and `--no-color` turn it off; never color
  output that is not a terminal.
- `--json` prints exactly one JSON document on standard output; everything else goes to
  standard error.
- Errors go to standard error in three parts: what failed, why, what to do.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from typing import Any, TextIO

from pydantic import BaseModel


@dataclass
class Output:
    json_mode: bool = False
    color: bool = True
    quiet: bool = False
    verbose: bool = False

    @classmethod
    def create(cls, *, json_mode: bool, no_color: bool, quiet: bool, verbose: bool) -> Output:
        color = not no_color and "NO_COLOR" not in os.environ
        return cls(json_mode=json_mode, color=color, quiet=quiet, verbose=verbose)

    def _stream(self) -> TextIO:
        # In JSON mode, human text never touches standard output.
        return sys.stderr if self.json_mode else sys.stdout

    def _paint(self, text: str, code: str, stream: TextIO) -> str:
        if self.color and stream.isatty():
            return f"\033[{code}m{text}\033[0m"
        return text

    def line(self, text: str = "") -> None:
        if not self.quiet:
            print(text, file=self._stream())

    def ok(self, text: str) -> None:
        stream = self._stream()
        if not self.quiet:
            print(f"{self._paint('ok', '36', stream)}    {text}", file=stream)

    def fail(self, text: str) -> None:
        stream = self._stream()
        print(f"{self._paint('FAIL', '33', stream)}  {text}", file=stream)

    def note(self, text: str) -> None:
        """Something the person should know before going on; not a failure."""
        stream = self._stream()
        if not self.quiet:
            print(f"{self._paint('note', '33', stream)}  {text}", file=stream)

    def next_step(self, text: str) -> None:
        """The dim closing line naming the obvious next command."""
        stream = self._stream()
        print(self._paint(text, "2", stream), file=stream)

    def error(self, what: str, why: str, fix: str) -> None:
        for part in (what, why, fix):
            print(part, file=sys.stderr)

    def document(self, value: BaseModel | dict[str, Any] | list[Any]) -> None:
        """The one JSON document a --json command prints."""
        if isinstance(value, BaseModel):
            text = value.model_dump_json(indent=2)
        else:
            text = json.dumps(value, indent=2, default=str)
        print(text, file=sys.stdout)
