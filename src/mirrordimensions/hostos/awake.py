# SPDX-License-Identifier: Apache-2.0
"""Keep the host awake during long operations, and notice if it slept anyway."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Generator
from contextlib import contextmanager


@contextmanager
def keep_awake(reason: str) -> Generator[None]:
    """Prevent idle sleep while the block runs (decision 0003)."""
    process: subprocess.Popen[bytes] | None = None
    if sys.platform == "darwin" and shutil.which("caffeinate"):
        process = subprocess.Popen(["caffeinate", "-i", "-w", str(os.getpid())])
    elif sys.platform.startswith("linux") and shutil.which("systemd-inhibit"):
        process = subprocess.Popen(
            [
                "systemd-inhibit",
                "--what=sleep:idle",
                f"--why={reason}",
                "--mode=block",
                "sleep",
                "infinity",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    elif sys.platform == "win32":
        import ctypes

        es_continuous, es_system_required = 0x80000000, 0x00000001
        ctypes.windll.kernel32.SetThreadExecutionState(es_continuous | es_system_required)  # type: ignore[attr-defined]
    try:
        yield
    finally:
        if process is not None:
            process.terminate()
        if sys.platform == "win32":
            import ctypes

            ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)  # type: ignore[attr-defined]


class SleepDetector:
    """Detects a host sleep as a jump between wall-clock and monotonic time.

    The monotonic clock stops while the host sleeps (macOS, Linux); the wall clock does
    not, so their difference grows by the length of the sleep.
    """

    def __init__(
        self,
        threshold_s: float = 2.0,
        wall: Callable[[], float] = time.time,
        mono: Callable[[], float] = time.monotonic,
    ) -> None:
        self._wall = wall
        self._mono = mono
        self.threshold_s = threshold_s
        self._base = wall() - mono()

    def slept_for(self) -> float:
        """Seconds of sleep detected since creation (0 if none above the threshold)."""
        jump = (self._wall() - self._mono()) - self._base
        return jump if jump > self.threshold_s else 0.0
