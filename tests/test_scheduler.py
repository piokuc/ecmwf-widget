"""The ECMWF publication schedule."""

from __future__ import annotations

import datetime as dt

from ecmwf_widget import scheduler


def test_cycle_times_are_six_hours_apart():
    now = dt.datetime(2026, 10, 21, 14, 30)
    times = scheduler.cycle_times(now)
    assert len(times) == 13
    assert times[0] < times[1]
    assert (times[1] - times[0]) == dt.timedelta(hours=6)
    # The list grows in time through ``now``.
    assert any(t <= now for t in times)
    assert any(t > now for t in times)


def test_cycle_times_are_aligned_to_the_cycles():
    now = dt.datetime(2026, 10, 21, 14, 30)
    for cycle in scheduler.cycle_times(now):
        assert cycle.minute == 0 and cycle.second == 0
        assert cycle.hour % 6 == 0


def test_current_cycle_floors_to_the_last_cycle():
    assert scheduler.current_cycle(dt.datetime(2026, 10, 21, 14, 30)) == dt.datetime(2026, 10, 21, 12)
    assert scheduler.current_cycle(dt.datetime(2026, 10, 21, 0, 59)) == dt.datetime(2026, 10, 21, 0)


def test_next_cycle_at_or_after_now():
    now = dt.datetime(2026, 10, 21, 14, 30)
    assert scheduler.next_cycle(now) == dt.datetime(2026, 10, 21, 18)
    exactly = dt.datetime(2026, 10, 21, 18, 0)
    assert scheduler.next_cycle(exactly) == exactly


def test_next_expected_is_cycle_plus_delay():
    now = dt.datetime(2026, 10, 21, 14, 30)
    # The 06 UTC cycle of today published eight hours and forty minutes
    # later is 14:40 UTC, still in the future at 14:30.
    expected = scheduler.next_expected(now, dt.timedelta(hours=8, minutes=40))
    assert expected == dt.datetime(2026, 10, 21, 14, 40)


def test_next_expected_moves_to_the_next_cycle_once_the_delay_passed():
    now = dt.datetime(2026, 10, 21, 21, 0)
    expected = scheduler.next_expected(now, dt.timedelta(hours=8, minutes=40))
    # 18 UTC + 8h40m is 02:40 tomorrow.
    assert expected == dt.datetime(2026, 10, 22, 2, 40)


def test_next_expected_skips_over_past_cycles():
    delay = dt.timedelta(hours=8, minutes=40)
    # At 10:00 UTC the 00 UTC cycle is already expected (08:40, in the
    # past), the 06 UTC cycle is next at 14:40.
    now = dt.datetime(2026, 10, 21, 10, 0)
    assert scheduler.next_expected(now, delay) == dt.datetime(2026, 10, 21, 14, 40)


def test_next_expected_exactly_at_the_expected_time_moves_on():
    delay = dt.timedelta(hours=8, minutes=40)
    now = dt.datetime(2026, 10, 21, 20, 40)
    # The expected time itself counts as not yet available, the next one
    # that is strictly in the future is the 18 UTC cycle at 02:40.
    assert scheduler.next_expected(now, delay) == dt.datetime(2026, 10, 22, 2, 40)
