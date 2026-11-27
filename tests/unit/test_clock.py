# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
"""The world's offsets land in office hours, in order, never in the future."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta

from mirrordimensions.world.clock import WorkClock


def test_offsets_land_in_office_hours_in_order() -> None:
    now = datetime(2026, 11, 27, 1, 30, 12, tzinfo=UTC)  # a Friday night in New York
    clock = WorkClock(now, -300)
    previous = now + timedelta(seconds=1)
    seconds: Counter[int] = Counter()
    for ago in range(1, 180 * 24 * 60, 89):
        placed = clock.at(ago, f"item:{ago}")
        local = placed - timedelta(hours=5)
        assert local.weekday() < 5
        assert timedelta(hours=8, minutes=30) <= local - local.replace(hour=0, minute=0, second=0)
        assert local.hour < 18
        assert placed < previous
        previous = placed
        seconds[placed.second] += 1
    assert len(seconds) > 50  # not every item on the same second
    assert clock.at(0, "x") == now.replace(microsecond=0)


def test_history_spans_about_the_same_calendar_time() -> None:
    now = datetime(2026, 6, 3, 15, 0, tzinfo=UTC)
    oldest = WorkClock(now, 0).at(180 * 24 * 60, "x")
    assert 170 <= (now - oldest).days <= 190


def test_office_hours() -> None:
    clock = WorkClock(datetime(2026, 11, 27, 2, 2, tzinfo=UTC), -300)  # Thu 21:02 local
    assert not clock.in_hours()
    assert clock.in_hours(datetime(2026, 11, 26, 15, 0, tzinfo=UTC))  # Thu 10:00 local
    assert not clock.in_hours(datetime(2026, 11, 28, 15, 0, tzinfo=UTC))  # Saturday
    assert clock.in_hours(clock.at(20, "delivery"))
    assert f"{clock.local():%a %H:%M}" == "Thu 21:02"
