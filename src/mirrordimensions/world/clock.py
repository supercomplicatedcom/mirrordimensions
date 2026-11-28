# SPDX-License-Identifier: Apache-2.0
"""When things happened: the world's offsets placed on the company's working week.

The world is defined by offsets in minutes (`ago`). Placing an offset at `now - ago` on the
wall clock gives a history with people committing at 3 a.m. on Sundays, and every item
sharing the seconds of the moment the world was seeded. Here an offset is read instead as
a share of working time: counted back from `now` through weekday office hours in the
company's time zone, scaled so that the history still spans the same number of calendar
days. Order is kept (a later offset is never placed before an earlier one, for offsets a
minute or more apart), nothing lands in the future, and each item gets its own seconds
from its key. Deterministic: the same `now`, offset, key and time zone give the same time.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

DAY_START = timedelta(hours=8, minutes=30)  # local
DAY_END = timedelta(hours=18)
WORK_DAY_S = (DAY_END - DAY_START).total_seconds()
WORK_WEEK_S = 5 * WORK_DAY_S
# Working seconds per calendar second, so that N days of offsets span about N days.
RATIO = WORK_WEEK_S / (7 * 24 * 3600)


def _jitter(key: str) -> int:
    return int.from_bytes(hashlib.sha256(key.encode()).digest()[:4], "big") % 60


class WorkClock:
    def __init__(self, now: datetime, utc_offset_minutes: int = 0) -> None:
        self.now = now.astimezone(UTC).replace(microsecond=0)
        self.offset = timedelta(minutes=utc_offset_minutes)

    def in_hours(self, when: datetime | None = None) -> bool:
        """Whether `when` (default now) falls in the company's office hours."""
        local = (when or self.now).astimezone(UTC) + self.offset
        since_midnight = local - local.replace(hour=0, minute=0, second=0, microsecond=0)
        return local.weekday() < 5 and DAY_START <= since_midnight < DAY_END

    def local(self, when: datetime | None = None) -> datetime:
        """`when` (default now) on the company's wall clock."""
        return (when or self.now).astimezone(UTC) + self.offset

    def at(self, ago_minutes: int, key: str = "") -> datetime:
        """The UTC time of something `ago_minutes` before now, in working hours."""
        if ago_minutes <= 0:
            return self.now
        need = (ago_minutes * 60 + _jitter(key)) * RATIO
        t = self.now + self.offset  # local wall time, kept as a naive-equivalent aware value
        if need > 2 * WORK_WEEK_S:  # whole weeks hold exactly one week's working time
            weeks = int(need // WORK_WEEK_S) - 1
            need -= weeks * WORK_WEEK_S
            t -= timedelta(days=7 * weeks)
        while True:
            day0 = t.replace(hour=0, minute=0, second=0, microsecond=0)
            if day0.weekday() < 5:
                start, end = day0 + DAY_START, day0 + DAY_END
                hi = min(t, end)
                if hi > start:
                    available = (hi - start).total_seconds()
                    if need <= available:
                        placed = hi - timedelta(seconds=need)
                        return (placed - self.offset).replace(microsecond=0)
                    need -= available
            t = day0 - timedelta(seconds=1)

    def ms(self, ago_minutes: int, key: str = "") -> int:
        """Milliseconds, as chat stores them; the last three digits vary by key too."""
        base = int(self.at(ago_minutes, key).timestamp() * 1000)
        return base if ago_minutes <= 0 else base + _jitter("ms:" + key) * 16

    def unix(self, ago_minutes: int, key: str = "") -> int:
        return int(self.at(ago_minutes, key).timestamp())
