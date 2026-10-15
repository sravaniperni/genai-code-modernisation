"""Execution history: an append-only log of job attempts kept in SQLite."""

from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone

from jobqueue.clock import ensure_utc
from jobqueue.job import Job

SCHEMA = """CREATE TABLE IF NOT EXISTS attempts (
    job_id TEXT NOT NULL, name TEXT NOT NULL, attempt INTEGER NOT NULL, outcome TEXT NOT NULL,
    started_at TIMESTAMP NOT NULL, finished_at TIMESTAMP NOT NULL, error TEXT)"""
COLUMNS = "job_id, name, attempt, outcome, started_at, finished_at, error"


@dataclass(frozen=True)
class Attempt:
    job_id: str
    name: str
    attempt: int
    outcome: str
    started_at: datetime
    finished_at: datetime
    error: str | None


def _to_db(value: datetime) -> str:
    """UTC as ``YYYY-MM-DD HH:MM:SS[.ffffff]`` text, which sorts chronologically."""
    return value.astimezone(timezone.utc).replace(tzinfo=None).isoformat(" ")


def _from_db(value: str) -> datetime:
    return ensure_utc(datetime.fromisoformat(value))


class ExecutionHistory:
    """Records every attempt made by an :class:`~jobqueue.executor.Executor`; ``path`` may be a file."""

    def __init__(self, path: str = ":memory:"):
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock, self._conn:
            self._conn.execute(SCHEMA)

    def record(self, job: Job, outcome: str, started_at: datetime, finished_at: datetime,
               error: str | None = None) -> None:
        row = (job.id, job.name, job.attempts, outcome, _to_db(started_at), _to_db(finished_at), error)
        with self._lock, self._conn:
            self._conn.execute(f"INSERT INTO attempts ({COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?)", row)

    def attempts(self, job_id: str) -> list[Attempt]:
        """All attempts of one job, oldest first."""
        with self._lock:
            rows = self._conn.execute(f"SELECT {COLUMNS} FROM attempts WHERE job_id = ? ORDER BY attempt, started_at",
                                      (job_id,)).fetchall()
        return [Attempt(*row[:4], _from_db(row[4]), _from_db(row[5]), row[6]) for row in rows]

    def close(self) -> None:
        self._conn.close()
