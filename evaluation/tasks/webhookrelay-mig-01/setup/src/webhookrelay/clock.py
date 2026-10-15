"""Clock abstraction and UTC timestamp helpers.

Every timestamp the relay stores or emits is UTC, held as a naive datetime. Components take a clock
object with a ``now()`` method so that tests, replays and dry runs can work against a fixed point in time.
"""

from __future__ import annotations

import calendar
from datetime import datetime, timedelta, timezone

UTC = timezone.utc


class SystemClock:
    """The wall clock, in UTC."""

    def now(self) -> datetime:
        return datetime.utcnow()


class FixedClock:
    """A clock that only moves when told to."""

    def __init__(self, start: datetime):
        self._now = ensure_utc(start)

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> datetime:
        self._now = self._now + timedelta(seconds=seconds)
        return self._now


def ensure_utc(value: datetime) -> datetime:
    """Return ``value`` as a naive UTC datetime. Aware datetimes are converted to UTC first."""
    if value.tzinfo is not None:
        value = value.astimezone(UTC).replace(tzinfo=None)
    return value


def from_epoch(seconds: float) -> datetime:
    """Convert a Unix timestamp (as sent in signature headers) to a UTC datetime."""
    return datetime.utcfromtimestamp(seconds)


def to_epoch(value: datetime) -> int:
    """Whole seconds since the Unix epoch."""
    return calendar.timegm(ensure_utc(value).utctimetuple())


def isoformat_z(value: datetime | None) -> str | None:
    """ISO-8601 with second precision and a ``Z`` suffix, e.g. ``2026-01-01T12:00:00Z``."""
    if value is None:
        return None
    return ensure_utc(value).replace(microsecond=0).isoformat() + "Z"
