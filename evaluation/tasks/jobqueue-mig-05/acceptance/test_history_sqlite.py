import sqlite3
from datetime import datetime, timedelta, timezone

from jobqueue.clock import FrozenClock
from jobqueue.executor import Executor
from jobqueue.history import ExecutionHistory
from jobqueue.job import Job
from jobqueue.queue import JobQueue
from jobqueue.registry import HandlerRegistry
from jobqueue.retry import RetryPolicy

T0 = datetime(2024, 5, 6, 8, 0, 0, tzinfo=timezone.utc)


def test_round_trip_keeps_exact_utc_times():
    history = ExecutionHistory()
    job = Job(name="resize", id="job-1", attempts=1)
    history.record(job, "retrying", T0, T0 + timedelta(seconds=1, microseconds=1), "IOError: disk full")
    job.attempts = 2
    history.record(job, "succeeded", T0 + timedelta(minutes=5), T0 + timedelta(minutes=5, seconds=3))
    first, second = history.attempts("job-1")
    assert (first.attempt, first.outcome, first.error, second.attempt, second.outcome, second.error) == (
        1, "retrying", "IOError: disk full", 2, "succeeded", None)
    assert first.started_at == T0 and first.finished_at == T0 + timedelta(seconds=1, microseconds=1)
    assert second.finished_at == T0 + timedelta(minutes=5, seconds=3)
    for value in (first.started_at, first.finished_at, second.started_at, second.finished_at):
        assert value.tzinfo is not None and value.utcoffset() == timedelta(0)


def test_other_time_zones_are_stored_as_the_same_instant():
    history = ExecutionHistory()
    tokyo = timezone(timedelta(hours=9))
    start = datetime(2024, 5, 6, 17, 0, 0, 500, tzinfo=tokyo)
    history.record(Job(name="x", id="j", attempts=1), "succeeded", start, start + timedelta(seconds=2))
    [attempt] = history.attempts("j")
    assert attempt.started_at == datetime(2024, 5, 6, 8, 0, 0, 500, tzinfo=timezone.utc)
    assert attempt.started_at.utcoffset() == timedelta(0)


def test_files_can_be_reopened(tmp_path):
    path = str(tmp_path / "history.sqlite")
    history = ExecutionHistory(path)
    history.record(Job(name="x", id="j", attempts=1), "failed", T0, T0 + timedelta(milliseconds=1500), "boom")
    history.close()
    reopened = ExecutionHistory(path)
    [attempt] = reopened.attempts("j")
    assert (attempt.started_at, attempt.finished_at, attempt.error) == (T0, T0 + timedelta(seconds=1.5), "boom")
    reopened.close()


def test_existing_history_files_remain_readable(tmp_path):
    path = str(tmp_path / "legacy.sqlite")
    ExecutionHistory(path).close()
    conn = sqlite3.connect(path)
    conn.executemany(
        "INSERT INTO attempts (job_id, name, attempt, outcome, started_at, finished_at, error) VALUES (?, ?, ?, ?, ?, ?, ?)",
        [("old", "resize", 1, "retrying", "2024-05-06 07:59:58", "2024-05-06 07:59:59.250000", "timeout"),
         ("old", "resize", 2, "succeeded", "2024-05-06 08:01:00", "2024-05-06 08:01:02", None)],
    )
    conn.commit()
    conn.close()
    history = ExecutionHistory(path)
    first, second = history.attempts("old")
    assert first.started_at == datetime(2024, 5, 6, 7, 59, 58, tzinfo=timezone.utc)
    assert first.finished_at == datetime(2024, 5, 6, 7, 59, 59, 250000, tzinfo=timezone.utc)
    assert second.finished_at == datetime(2024, 5, 6, 8, 1, 2, tzinfo=timezone.utc)
    history.record(Job(name="resize", id="old", attempts=3), "succeeded", T0, T0)
    assert [a.attempt for a in history.attempts("old")] == [1, 2, 3]


def test_executor_records_every_attempt():
    history = ExecutionHistory()
    registry = HandlerRegistry()
    calls = []

    def flaky(payload):
        calls.append(1)
        if len(calls) == 1:
            raise ConnectionError("upstream unavailable")
        return "ok"

    registry.register("flaky", flaky)
    clock = FrozenClock(T0)
    queue = JobQueue(registry=registry, clock=clock)
    job = queue.enqueue("flaky", max_attempts=3)
    executor = Executor(queue.store, registry, clock=clock, history=history, retry_policy=RetryPolicy(base_delay=1))
    executor.execute(queue.store.claim_next(clock.now(), "w"))
    clock.advance(seconds=2)
    executor.execute(queue.store.claim_next(clock.now(), "w"))
    first, second = history.attempts(job.id)
    assert (first.outcome, second.outcome) == ("retrying", "succeeded")
    assert "upstream unavailable" in first.error and second.error is None
    assert (first.started_at, second.started_at) == (T0, T0 + timedelta(seconds=2))
