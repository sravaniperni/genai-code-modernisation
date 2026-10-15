"""Job records, states and priorities."""

from __future__ import annotations

import dataclasses
import itertools
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum, StrEnum
from typing import Any

from jobqueue import clock

_sequence = itertools.count(1)


class JobState(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in (JobState.SUCCEEDED, JobState.FAILED, JobState.CANCELLED)


class Priority(IntEnum):
    """Jobs with a higher priority are claimed first."""

    LOW = 1
    NORMAL = 5
    HIGH = 8
    CRITICAL = 9


@dataclass
class Job:
    """A unit of work: run handler ``name`` with ``payload``."""

    name: str
    payload: dict[str, Any] = field(default_factory=dict)
    queue: str = "default"
    priority: int = Priority.NORMAL
    max_attempts: int = 3
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    state: JobState = JobState.PENDING
    attempts: int = 0
    run_at: datetime | None = None
    created_at: datetime = field(default_factory=clock.utcnow)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    last_error: str | None = None
    result: Any = None
    worker: str | None = None
    unique_key: str | None = None
    seq: int = field(default_factory=lambda: next(_sequence))

    def is_due(self, now: datetime) -> bool:
        return self.state == JobState.PENDING and (self.run_at is None or self.run_at <= now)

    def copy(self) -> Job:
        return dataclasses.replace(self, payload=dict(self.payload))

    def summary(self) -> dict[str, Any]:
        """A JSON-friendly view used by webhooks and the CLI."""
        data = {key: getattr(self, key) for key in ("id", "name", "queue", "attempts", "max_attempts", "last_error")}
        times = {key: getattr(self, key) for key in ("run_at", "created_at", "finished_at")}
        data.update({key: value.isoformat() if value else None for key, value in times.items()})
        return {**data, "state": self.state.value, "priority": int(self.priority)}
