"""The producer-facing queue API."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import timedelta
from typing import Any

from jobqueue.clock import Clock, SystemClock
from jobqueue.errors import DuplicateJob
from jobqueue.job import Job
from jobqueue.payload import DEFAULT_MAX_PAYLOAD_BYTES, check_payload_size
from jobqueue.registry import HandlerRegistry
from jobqueue.spec import JobSpec, parse_spec, validate_payload
from jobqueue.store import JobStore, MemoryJobStore


class JobQueue:
    """Validates submissions and stores them as jobs.

    With a ``registry``, submissions are checked against the handlers and their payload schemas. Every
    listener (for example a :class:`~jobqueue.workers.WorkerPool`) is called with each job that becomes runnable.
    """

    def __init__(self, store: JobStore | None = None, *, registry: HandlerRegistry | None = None,
                 clock: Clock | None = None, max_payload_bytes: int = DEFAULT_MAX_PAYLOAD_BYTES):
        self.store = store if store is not None else MemoryJobStore()
        self.registry = registry
        self.clock = clock or SystemClock()
        self.max_payload_bytes = max_payload_bytes
        self.listeners: list[Callable[[Job], None]] = []

    def enqueue(self, name: str, payload: Mapping[str, Any] | None = None, **options: Any) -> Job:
        """Submit a job; ``options`` are :class:`~jobqueue.spec.JobSpec` fields (queue, priority, delay ...)."""
        return self.submit(parse_spec({"name": name, "payload": dict(payload or {}), **options}))

    def submit(self, spec: JobSpec) -> Job:
        payload = dict(spec.payload)
        if self.registry is not None:
            schema = self.registry.get(spec.name).schema
            payload = validate_payload(schema, payload) if schema is not None else payload
        check_payload_size(payload, self.max_payload_bytes)
        if spec.unique_key is not None and (existing := self.store.find_active(spec.unique_key)) is not None:
            raise DuplicateJob(spec.unique_key, existing.id)
        now = self.clock.now()
        run_at = spec.run_at or (now + timedelta(seconds=spec.delay) if spec.delay else None)
        job = Job(name=spec.name, payload=payload, queue=spec.queue, priority=spec.priority,
                  max_attempts=spec.max_attempts, run_at=run_at, created_at=now, unique_key=spec.unique_key)
        self.store.add(job)
        self._announce(job)
        return job

    def get(self, job_id: str) -> Job:
        return self.store.get(job_id)

    def _announce(self, job: Job) -> None:
        for listener in list(self.listeners):
            listener(job)
