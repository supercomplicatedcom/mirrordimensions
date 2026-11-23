# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""Make the command's output the same bytes on every host.

When output is piped or redirected, Python on Windows encodes text with the legacy code
page (for example cp1252), so the same command prints different bytes there. Standard
output and standard error are switched to UTF-8 on every host.
"""

from __future__ import annotations

import io
import sys


def use_utf8_streams() -> None:
    for stream in (sys.stdout, sys.stderr):
        if (
            isinstance(stream, io.TextIOWrapper)
            and stream.encoding.lower().replace("-", "") != "utf8"
        ):
            stream.reconfigure(encoding="utf-8", errors="replace")
