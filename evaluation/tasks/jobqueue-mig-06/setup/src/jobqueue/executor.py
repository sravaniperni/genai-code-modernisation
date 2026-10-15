"""Runs claimed jobs and records their outcome."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from jobqueue.aio import run_handler
from jobqueue.clock import Clock, SystemClock
from jobqueue.errors import HandlerNotFound
from jobqueue.job import Job, JobState
from jobqueue.registry import HandlerRegistry
from jobqueue.retry import RetryPolicy
from jobqueue.store import JobStore

log = logging.getLogger("jobqueue.executor")


class Executor:
    """Executes RUNNING jobs claimed from ``store``.

    A failing job is retried per ``retry_policy`` until it has used ``max_attempts`` attempts, then marked
    FAILED; a job without a registered handler fails at once. ``notifier`` (a webhook notifier) hears about
    finished jobs, ``history`` about every attempt; notification problems never change a job's outcome.
    """

    def __init__(self, store: JobStore, registry: HandlerRegistry, *, clock: Clock | None = None,
                 retry_policy: RetryPolicy | None = None, notifier: Any = None, history: Any = None):
        self.store = store
        self.registry = registry
        self.clock = clock or SystemClock()
        self.retry_policy = retry_policy or RetryPolicy()
        self.notifier = notifier
        self.history = history

    def execute(self, job: Job) -> Job:
        """Run ``job`` (which must have been claimed) and persist the outcome; returns the updated job."""
        started = job.started_at or self.clock.now()
        try:
            info = self.registry.get(job.name)
            result = run_handler(info.func, dict(job.payload))
        except HandlerNotFound as exc:
            self._fail(job, exc, retry=False)
        except Exception as exc:
            self._fail(job, exc, retry=True)
        else:
            job.state, job.result, job.last_error = JobState.SUCCEEDED, result, None
            job.finished_at = self.clock.now()
            self.store.update(job)
        if self.history is not None:
            outcome = {JobState.SUCCEEDED: "succeeded", JobState.PENDING: "retrying"}.get(job.state, "failed")
            self.history.record(job, outcome, started, self.clock.now(), job.last_error)
        if self.notifier is not None and job.state.is_terminal:
            try:
                self.notifier.notify(job)
            except Exception as exc:
                log.warn("completion notification for job %s failed: %s", job.id, exc)
        return job

    def _fail(self, job: Job, exc: Exception, *, retry: bool) -> None:
        job.last_error = f"{type(exc).__name__}: {exc}"
        now = self.clock.now()
        if retry and job.attempts < job.max_attempts:
            delay = self.retry_policy.delay_for(job.attempts)
            job.state, job.run_at, job.worker = JobState.PENDING, now + timedelta(seconds=delay), None
            log.warn("job %s (%s) failed on attempt %d of %d, retrying in %.1fs: %s",
                        job.id, job.name, job.attempts, job.max_attempts, delay, job.last_error)
        else:
            job.state, job.finished_at = JobState.FAILED, now
            log.error("job %s (%s) failed after %d attempt(s): %s", job.id, job.name, job.attempts, job.last_error)
        self.store.update(job)
