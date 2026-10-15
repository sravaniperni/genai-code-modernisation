"""Recurring jobs driven by cron schedules."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import arrow

from jobqueue.clock import from_timestamp
from jobqueue.cron import CronSchedule
from jobqueue.job import Job
from jobqueue.queue import JobQueue


@dataclass
class RecurringJob:
    key: str
    job_name: str
    schedule: CronSchedule
    payload: dict[str, Any] = field(default_factory=dict)
    options: dict[str, Any] = field(default_factory=dict)
    next_fire: int = 0  # POSIX timestamp of the next fire time
    fired: int = 0


class RecurringScheduler:
    """Enqueues a job on ``queue`` each time a registered schedule fires; call :meth:`tick` periodically.

    Missed fire times are coalesced: a late entry runs once and is rescheduled after the current time. Each
    job's payload records the fire time it was created for under ``scheduled_for``.
    """

    def __init__(self, queue: JobQueue):
        self.queue = queue
        self._entries: dict[str, RecurringJob] = {}
        self._lock = threading.Lock()

    def add(self, key: str, expression: str, job_name: str, payload: dict[str, Any] | None = None,
            *, tz: str = "UTC", **options: Any) -> RecurringJob:
        schedule = CronSchedule(expression, tz)
        entry = RecurringJob(key, job_name, schedule, dict(payload or {}), options)
        entry.next_fire = schedule.next_timestamp(self.queue.clock.now())
        with self._lock:
            if key in self._entries:
                raise ValueError(f"recurring job {key!r} already exists")
            self._entries[key] = entry
        return entry

    def tick(self, now: datetime | None = None) -> list[Job]:
        """Enqueue every entry whose fire time is not after ``now``; returns the new jobs."""
        now = now or self.queue.clock.now()
        now_ts = arrow.get(now).timestamp
        created: list[Job] = []
        with self._lock:
            for entry in sorted(self._entries.values(), key=lambda item: item.key):
                if entry.next_fire > now_ts:
                    continue
                payload = {**entry.payload, "scheduled_for": from_timestamp(entry.next_fire).isoformat()}
                created.append(self.queue.enqueue(entry.job_name, payload, **entry.options))
                entry.fired += 1
                entry.next_fire = entry.schedule.next_timestamp(now)
        return created
