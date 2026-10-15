"""Clock abstraction and UTC timestamp helpers.

Every timestamp the relay stores or emits is in UTC. Components take a clock object with a ``now()``
method so that tests, replays and dry runs can work against a fixed point in time.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

UTC = timezone.utc


class SystemClock:
    """The wall clock, as timezone-aware UTC datetimes."""

    def now(self) -> datetime:
        return datetime.now(UTC)


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
    """Return ``value`` in UTC. Naive datetimes are taken to already be UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def from_epoch(seconds: float) -> datetime:
    """Convert a Unix timestamp (as sent in signature headers) to a UTC datetime."""
    return datetime.fromtimestamp(seconds, UTC)


def to_epoch(value: datetime) -> int:
    """Whole seconds since the Unix epoch."""
    return int(ensure_utc(value).timestamp())


def isoformat_z(value: datetime | None) -> str | None:
    """ISO-8601 with second precision and a ``Z`` suffix, e.g. ``2026-01-01T12:00:00Z``."""
    if value is None:
        return None
    return ensure_utc(value).strftime("%Y-%m-%dT%H:%M:%SZ")
