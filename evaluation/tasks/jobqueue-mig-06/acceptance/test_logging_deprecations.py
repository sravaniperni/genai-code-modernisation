import logging
import os
import re
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from jobqueue.clock import FrozenClock
from jobqueue.errors import WebhookError
from jobqueue.executor import Executor
from jobqueue.job import JobState
from jobqueue.queue import JobQueue
from jobqueue.registry import HandlerRegistry
from jobqueue.retry import RetryPolicy
from jobqueue.workers import WorkerPool

T0 = datetime(2024, 5, 6, 8, 0, tzinfo=timezone.utc)
TIMEOUT = 10


class BrokenNotifier:
    def notify(self, job):
        raise WebhookError("receiver returned HTTP 502", status=502)


def warnings_from(caplog, logger):
    return [r for r in caplog.records if r.name == logger and r.levelno == logging.WARNING]


def setup(**executor_kwargs):
    registry = HandlerRegistry()
    clock = FrozenClock(T0)
    queue = JobQueue(registry=registry, clock=clock)
    executor = Executor(queue.store, registry, clock=clock, **executor_kwargs)
    return registry, clock, queue, executor


def test_retry_is_scheduled_and_logged(caplog):
    registry, clock, queue, executor = setup(retry_policy=RetryPolicy(base_delay=30))
    attempts = []
    registry.register("sync", lambda payload: attempts.append(1) or (len(attempts) > 1 or 1 / 0))
    job = queue.enqueue("sync", max_attempts=3)
    with caplog.at_level(logging.WARNING):
        executor.execute(queue.store.claim_next(clock.now(), "w"))
    pending = queue.get(job.id)
    assert pending.state == JobState.PENDING and pending.run_at == T0 + timedelta(seconds=30)
    [record] = warnings_from(caplog, "jobqueue.executor")
    assert job.id in record.getMessage()
    clock.advance(seconds=30)
    executor.execute(queue.store.claim_next(clock.now(), "w"))
    assert queue.get(job.id).state == JobState.SUCCEEDED


def test_notification_failures_are_logged_not_raised(caplog):
    registry, clock, queue, executor = setup(notifier=BrokenNotifier())
    registry.register("ok", lambda payload: "fine")
    job = queue.enqueue("ok")
    with caplog.at_level(logging.WARNING):
        executor.execute(queue.store.claim_next(clock.now(), "w"))
    assert queue.get(job.id).state == JobState.SUCCEEDED
    [record] = warnings_from(caplog, "jobqueue.executor")
    assert job.id in record.getMessage()


def test_stop_timeout_is_logged(caplog):
    registry, clock, queue, executor = setup()
    entered, release = threading.Event(), threading.Event()
    registry.register("slow", lambda payload: (entered.set(), release.wait(TIMEOUT)))
    pool = WorkerPool(queue, executor, size=1, poll_interval=0.05, name="logpool")
    pool.start()
    try:
        queue.enqueue("slow")
        assert entered.wait(TIMEOUT)
        with caplog.at_level(logging.WARNING):
            assert pool.stop(timeout=0.05) is False
        [record] = warnings_from(caplog, "jobqueue.workers")
        assert "logpool-1" in record.getMessage()
    finally:
        release.set()
        assert pool.stop(timeout=TIMEOUT)


def test_no_deprecated_warn_calls_remain():
    root = Path(os.environ["REPO_ROOT"]) / "src" / "jobqueue"
    offenders = [p.name for p in root.glob("*.py") if re.search(r"(?<!warnings)\.warn\(", p.read_text())]
    assert offenders == []
