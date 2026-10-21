"""The ECMWF publication schedule.

ECMWF produces deterministic forecasts on the fixed ``0, 6, 12, 18 UTC``
cycles. The open data portal does not publish them the moment the forecast
completes: the coarse 0.25 degree tier appears first, and the 0.1 degree
tier roughly two hours later, which lands about eight hours and forty
minutes after the cycle time.

Everything in this module works on :class:`~datetime.datetime` values in
UTC so callers can pass a fake ``now`` and be tested without sleeping.
"""

from __future__ import annotations

import datetime as dt

__all__ = [
    "CYCLES",
    "DEFAULT_DELAY",
    "cycle_times",
    "current_cycle",
    "next_cycle",
    "next_expected",
]

#: The deterministic cycles, in hours of the day.
CYCLES: tuple[int, ...] = (0, 6, 12, 18)

#: How long after the cycle time the 0.1 degree data is expected.
DEFAULT_DELAY = dt.timedelta(hours=8, minutes=40)


def _floor_to_cycle(moment: dt.datetime) -> dt.datetime:
    """The same day, rounded down to the newest cycle."""
    hour = (moment.hour // 6) * 6
    return moment.replace(hour=hour, minute=0, second=0, microsecond=0)


def current_cycle(now: dt.datetime) -> dt.datetime:
    """The cycle that is being produced at ``now``."""
    return _floor_to_cycle(now)


def next_cycle(now: dt.datetime) -> dt.datetime:
    """The next cycle time at or after ``now``."""
    floored = _floor_to_cycle(now)
    if floored == now:
        return floored
    return floored + dt.timedelta(hours=6)


def cycle_times(now: dt.datetime, back: int = 8) -> list[dt.datetime]:
    """The recent and upcoming cycle times.

    Four before ``now`` and four after, by default. The ones in the past
    are what the service can still backfill; the ones in the future are
    what the publisher waits for.
    """
    start = _floor_to_cycle(now)
    return [start + dt.timedelta(hours=6 * index) for index in range(-back, 5)]


def next_expected(now: dt.datetime, delay: dt.timedelta = DEFAULT_DELAY) -> dt.datetime:
    """When the next run is expected to be on the portal.

    For every recent and upcoming cycle, the cycle time plus the ``delay``
    of publication; the first of those times that is still in the future is
    the one to wait for.
    """
    for cycle in cycle_times(now):
        expected = cycle + delay
        if expected > now:
            return expected
    raise RuntimeError("no upcoming cycle found")  # pragma: no cover
