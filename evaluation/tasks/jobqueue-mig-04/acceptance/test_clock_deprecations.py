import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from jobqueue import clock
from jobqueue.executor import Executor
from jobqueue.job import Job, JobState
from jobqueue.queue import JobQueue
from jobqueue.registry import HandlerRegistry


def is_utc(value):
    return value.tzinfo is not None and value.utcoffset() == timedelta(0)


def test_utcnow_is_aware_utc_and_current():
    before = datetime.now(timezone.utc)
    now = clock.utcnow()
    system = clock.SystemClock().now()
    after = datetime.now(timezone.utc)
    assert is_utc(now) and is_utc(system)
    assert before <= now <= system <= after


def test_from_timestamp():
    assert clock.from_timestamp(0) == datetime(1970, 1, 1, tzinfo=timezone.utc)
    value = clock.from_timestamp(1714982415.25)
    assert value == datetime(2024, 5, 6, 8, 0, 15, 250000, tzinfo=timezone.utc) and is_utc(value)
    assert clock.from_timestamp(-86400) == datetime(1969, 12, 31, tzinfo=timezone.utc)
    assert is_utc(clock.from_timestamp(1_000_000_000))


def test_jobs_and_queue_use_aware_utc_times():
    before = datetime.now(timezone.utc)
    assert is_utc(Job(name="x").created_at)
    registry = HandlerRegistry()
    registry.register("echo", lambda payload: payload)
    queue = JobQueue(registry=registry)
    delayed = queue.enqueue("echo", {"v": 1}, delay=45)
    assert is_utc(delayed.created_at) and before <= delayed.created_at
    assert delayed.run_at - delayed.created_at == timedelta(seconds=45)
    now_job = queue.enqueue("echo", {"v": 2})
    Executor(queue.store, registry).execute(queue.store.claim_next(clock.utcnow(), "w"))
    done = queue.get(now_job.id)
    assert done.state == JobState.SUCCEEDED and is_utc(done.finished_at) and is_utc(done.started_at)
    assert done.created_at <= done.started_at <= done.finished_at <= datetime.now(timezone.utc)


def test_deprecated_calls_are_gone():
    source = (Path(os.environ["REPO_ROOT"]) / "src" / "jobqueue" / "clock.py").read_text()
    assert not re.search(r"\.utcnow\(\)|utcfromtimestamp\(", source)
