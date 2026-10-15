"""Time helpers. Every timestamp jobqueue stores is a timezone-aware UTC datetime."""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from typing import Protocol


def utcnow() -> datetime:
    """Return the current time as an aware UTC datetime."""
    return datetime.utcnow().replace(tzinfo=timezone.utc)


def from_timestamp(seconds: float) -> datetime:
    """Convert a POSIX timestamp to an aware UTC datetime."""
    return datetime.utcfromtimestamp(seconds).replace(tzinfo=timezone.utc)


def ensure_utc(value: datetime) -> datetime:
    """Interpret naive datetimes as UTC and convert aware ones to UTC."""
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return utcnow()


class FrozenClock:
    """A manually advanced clock for tests and simulations."""

    def __init__(self, start: datetime):
        self._now = ensure_utc(start)
        self._lock = threading.Lock()

    def now(self) -> datetime:
        with self._lock:
            return self._now

    def advance(self, seconds: float = 0.0, **kwargs: float) -> datetime:
        with self._lock:
            self._now += timedelta(seconds=seconds, **kwargs)
            return self._now
