"""Retry policy and the scheduler that re-attempts failed deliveries."""

from __future__ import annotations

import heapq
import itertools
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any

from .clock import UTC, SystemClock, ensure_utc, isoformat_z

log = logging.getLogger(__name__)

RETRYABLE_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504})


@dataclass(frozen=True)
class RetryPolicy:
    """Exponential backoff for failed deliveries.

    ``max_attempts`` counts every attempt including the first one. The retry that follows failed attempt
    number *n* (1-based) waits ``base_delay * factor ** (n - 1)`` seconds - 2s, 4s, 8s, ... with the
    defaults - but never longer than ``max_delay``.
    """

    max_attempts: int = 5
    base_delay: float = 2.0
    factor: float = 2.0
    max_delay: float = 300.0

    def should_retry(self, attempt: int, status: int | None) -> bool:
        """Whether a delivery whose attempt number ``attempt`` failed with ``status`` (``None`` for a
        connection error) should be tried again."""
        if attempt >= self.max_attempts:
            return False
        return status is None or status in RETRYABLE_STATUSES

    def delay_for(self, attempt: int) -> float:
        """Seconds to wait after failed attempt number ``attempt`` before the next one."""
        if attempt < 1:
            raise ValueError("attempt numbers start at 1")
        return min(self.max_delay, self.base_delay * self.factor ** (attempt - 1))


def parse_retry_after(value: str | None, now: datetime) -> datetime | None:
    """Interpret a ``Retry-After`` header (delta-seconds or an HTTP date) as an absolute UTC time."""
    if not value or not value.strip():
        return None
    value = value.strip()
    if value.isdigit():
        return ensure_utc(now) + timedelta(seconds=int(value))
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        return None
    return when.replace(tzinfo=UTC)


@dataclass(order=True)
class ScheduledRetry:
    due_at: datetime
    seq: int
    payload: Any = field(compare=False)


class RetryScheduler:
    """Holds failed deliveries until they are due and then hands them to ``callback``.

    ``run_pending()`` performs one pass. ``start()`` runs passes on a daemon worker thread every
    ``poll_interval`` seconds until ``stop()`` is called. Due times are stored in UTC.
    """

    def __init__(self, callback: Callable[[Any], Any], *, clock: Any = None, poll_interval: float = 1.0):
        self._callback = callback
        self._clock = clock or SystemClock()
        self._poll_interval = poll_interval
        self._heap: list[ScheduledRetry] = []
        self._lock = threading.Lock()
        self._seq = itertools.count()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def schedule(self, payload: Any, due_at: datetime) -> ScheduledRetry:
        item = ScheduledRetry(due_at.replace(tzinfo=UTC), next(self._seq), payload)
        with self._lock:
            heapq.heappush(self._heap, item)
        return item

    def pending(self) -> list[ScheduledRetry]:
        with self._lock:
            return sorted(self._heap)

    def run_pending(self) -> int:
        """Hand every due item to the callback; returns how many were due."""
        now = self._clock.now()
        due: list[ScheduledRetry] = []
        with self._lock:
            while self._heap and self._heap[0].due_at <= now:
                due.append(heapq.heappop(self._heap))
        for item in due:
            self._callback(item.payload)
        return len(due)

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive() and not self._stop.is_set()

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        thread = threading.Thread(target=self._run, name="webhookrelay-retry", daemon=True)
        thread.start()
        self._thread = thread

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)
        self._thread = None

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.run_pending()
            except Exception:  # keep the worker alive; the failure is logged
                log.exception("retry pass failed")
            self._stop.wait(self._poll_interval)

    def describe(self) -> dict[str, Any]:
        items, worker = self.pending(), self._thread.name if self._thread is not None else None
        next_due = isoformat_z(items[0].due_at) if items else None
        return {"running": self.running, "worker": worker, "pending": len(items), "next_due": next_due}
