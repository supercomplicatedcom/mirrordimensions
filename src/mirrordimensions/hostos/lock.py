# SPDX-License-Identifier: Apache-2.0
"""One writer at a time: a portable lock on `.mirror/lock`.

The OS lock (flock on POSIX, a byte-range lock on Windows) is released automatically if
the process dies, so a crash never leaves a stale lock. Who holds it is written to
`lock.json` beside it, so a second process can name the holder.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import IO, Self

from mirrordimensions.errors import LockHeldError
from mirrordimensions.hostos.files import write_text


class ProjectLock:
    def __init__(self, state_dir: Path, operation: str) -> None:
        self.path = state_dir / "lock"
        self.holder_path = state_dir / "lock.json"
        self.operation = operation
        self._handle: IO[bytes] | None = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(self.path, "a+b")  # noqa: SIM115  (kept open while held)
        if not _try_lock(handle):
            handle.close()
            raise LockHeldError(self._describe_holder())
        self._handle = handle
        write_text(
            self.holder_path,
            json.dumps(
                {
                    "operation": self.operation,
                    "pid": os.getpid(),
                    "since": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                }
            )
            + "\n",
        )

    def release(self) -> None:
        if self._handle is None:
            return
        self.holder_path.unlink(missing_ok=True)
        _unlock(self._handle)
        self._handle.close()
        self._handle = None

    def held(self) -> str | None:
        """The operation holding the lock now, or None if nobody does. Does not take it."""
        if not self.path.is_file():
            return None
        with open(self.path, "a+b") as handle:
            if _try_lock(handle):
                _unlock(handle)
                return None
        try:
            return str(json.loads(self.holder_path.read_text(encoding="utf-8"))["operation"])
        except (OSError, ValueError, KeyError):
            return "unknown"

    def _describe_holder(self) -> str:
        try:
            data = json.loads(self.holder_path.read_text(encoding="utf-8"))
            return f"`mirror {data['operation']}` (process {data['pid']}, since {data['since']})"
        except (OSError, ValueError, KeyError):
            return "another mirror process"

    def __enter__(self) -> Self:
        self.acquire()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.release()


if sys.platform == "win32":
    import msvcrt

    def _try_lock(handle: IO[bytes]) -> bool:
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True

    def _unlock(handle: IO[bytes]) -> None:
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def _try_lock(handle: IO[bytes]) -> bool:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return False
        return True

    def _unlock(handle: IO[bytes]) -> None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
