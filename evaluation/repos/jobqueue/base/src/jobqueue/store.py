"""Job store interface and the in-process implementation."""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from collections.abc import Sequence
from datetime import datetime

from jobqueue.errors import JobNotFound
from jobqueue.job import Job, JobState


def mark_running(job: Job, now: datetime, worker: str) -> None:
    """Apply the state change of a successful claim to ``job``."""
    job.state, job.started_at, job.worker = JobState.RUNNING, now, worker
    job.attempts += 1


class JobStore(ABC):
    """Persistence for jobs. Stores hand out copies; changes take effect when passed to :meth:`update`.

    :meth:`claim_next` picks the due job with the highest priority; jobs of equal priority are claimed in the
    order they were submitted. :meth:`list` returns jobs in submission order.
    """

    @abstractmethod
    def add(self, job: Job) -> None: ...

    @abstractmethod
    def get(self, job_id: str) -> Job: ...

    @abstractmethod
    def update(self, job: Job) -> None: ...

    @abstractmethod
    def claim_next(self, now: datetime, worker: str, queues: Sequence[str] | None = None) -> Job | None: ...

    @abstractmethod
    def list(self, *, state: JobState | None = None, queue: str | None = None,
             limit: int | None = None) -> list[Job]: ...

    @abstractmethod
    def find_active(self, unique_key: str) -> Job | None: ...

    def counts(self) -> dict[str, int]:
        result = {state.value: 0 for state in JobState}
        for job in self.list():
            result[job.state.value] += 1
        return result

    def queues(self) -> list[str]:
        return sorted({job.queue for job in self.list()})

    def close(self) -> None:
        """Release resources held by the store."""


class MemoryJobStore(JobStore):
    """A thread-safe store that keeps jobs in process memory."""

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def add(self, job: Job) -> None:
        with self._lock:
            if job.id in self._jobs:
                raise ValueError(f"duplicate job id {job.id}")
            self._jobs[job.id] = job.copy()

    def get(self, job_id: str) -> Job:
        with self._lock:
            if job_id not in self._jobs:
                raise JobNotFound(job_id)
            return self._jobs[job_id].copy()

    def update(self, job: Job) -> None:
        with self._lock:
            if job.id not in self._jobs:
                raise JobNotFound(job.id)
            self._jobs[job.id] = job.copy()

    def claim_next(self, now: datetime, worker: str, queues: Sequence[str] | None = None) -> Job | None:
        with self._lock:
            due = [job for job in self._jobs.values() if job.is_due(now) and (not queues or job.queue in queues)]
            if not due:
                return None
            job = min(due, key=lambda item: (-item.priority, item.created_at, item.seq))
            mark_running(job, now, worker)
            return job.copy()

    def list(self, *, state: JobState | None = None, queue: str | None = None,
             limit: int | None = None) -> list[Job]:
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda job: (job.created_at, job.seq))
        jobs = [job for job in jobs if (state is None or job.state == state) and (queue is None or job.queue == queue)]
        return [job.copy() for job in jobs[:limit]]

    def find_active(self, unique_key: str) -> Job | None:
        with self._lock:
            matches = [job for job in self._jobs.values() if job.unique_key == unique_key and not job.state.is_terminal]
        return matches[0].copy() if matches else None
