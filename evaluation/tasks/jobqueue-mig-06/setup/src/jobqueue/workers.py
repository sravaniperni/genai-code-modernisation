"""A pool of worker threads that claim and execute jobs."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Sequence

from jobqueue.executor import Executor
from jobqueue.job import Job
from jobqueue.queue import JobQueue

log = logging.getLogger("jobqueue.workers")


class WorkerPool:
    """Runs jobs from ``queue`` on ``size`` daemon threads named ``<name>-1`` ... ``<name>-<size>``.

    Idle workers sleep until a job is enqueued or ``poll_interval`` elapses. :meth:`stop` is graceful: workers
    finish their current job, then exit. ``on_job_done`` callbacks run in the worker thread after each job.
    """

    def __init__(self, queue: JobQueue, executor: Executor, *, size: int = 2,
                 queues: Sequence[str] | None = None, poll_interval: float = 1.0, name: str = "jobqueue-worker"):
        if size < 1:
            raise ValueError("a worker pool needs at least one worker")
        self.queue, self.executor, self.size, self.name = queue, executor, size, name
        self.queues, self.poll_interval = (list(queues) if queues else None), poll_interval
        self.on_job_done: list[Callable[[Job], None]] = []
        self._wakeup = threading.Condition()
        self._signals = 0
        self._stopping = threading.Event()
        self._threads: list[threading.Thread] = []
        queue.listeners.append(lambda job: self.wake())

    @property
    def running(self) -> bool:
        return bool(self._threads) and not self._stopping.is_set()

    def worker_names(self) -> list[str]:
        return [thread.name for thread in self._threads]

    def start(self) -> None:
        if self.running:
            raise RuntimeError("worker pool is already running")
        self._stopping.clear()
        self._threads = []
        for number in range(1, self.size + 1):
            thread = threading.Thread(target=self._run, name=f"{self.name}-{number}", daemon=True)
            thread.start()
            self._threads.append(thread)

    def stop(self, timeout: float | None = 30.0) -> bool:
        """Stop claiming jobs and wait for the workers to exit; ``False`` if some are still busy."""
        self._stopping.set()
        self.wake()
        deadline = None if timeout is None else time.monotonic() + timeout
        for thread in self._threads:
            thread.join(None if deadline is None else max(0.0, deadline - time.monotonic()))
        busy = [thread.name for thread in self._threads if thread.is_alive()]
        if busy:
            log.warn("worker pool %s: %s still busy after %ss", self.name, ", ".join(busy), timeout)
            return False
        self._threads = []
        return True

    def wake(self) -> None:
        with self._wakeup:
            self._signals += 1
            self._wakeup.notify_all()

    def run_once(self, worker: str = "inline") -> Job | None:
        """Claim and execute one due job in the calling thread; ``None`` when nothing is due."""
        job = self.queue.store.claim_next(self.queue.clock.now(), worker, self.queues)
        return self._process(job) if job is not None else None

    def drain(self, limit: int = 10_000) -> int:
        """Run due jobs in the calling thread until none is left; returns how many ran."""
        count = 0
        while count < limit and self.run_once() is not None:
            count += 1
        return count

    def _run(self) -> None:
        worker = threading.current_thread().name
        while not self._stopping.is_set():
            with self._wakeup:
                seen = self._signals
            job = self.queue.store.claim_next(self.queue.clock.now(), worker, self.queues)
            if job is not None:
                self._process(job)
                continue
            with self._wakeup:
                if self._signals == seen and not self._stopping.is_set():
                    self._wakeup.wait(self.poll_interval)

    def _process(self, job: Job) -> Job:
        try:
            job = self.executor.execute(job)
        except Exception:
            log.exception("worker crashed while executing job %s (%s)", job.id, job.name)
        for callback in list(self.on_job_done):
            callback(job)
        return job
