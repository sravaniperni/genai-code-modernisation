import threading
from datetime import datetime, timezone

from jobqueue.clock import FrozenClock
from jobqueue.executor import Executor
from jobqueue.history import ExecutionHistory
from jobqueue.job import JobState
from jobqueue.queue import JobQueue
from jobqueue.registry import HandlerRegistry
from jobqueue.store import MemoryJobStore
from jobqueue.workers import WorkerPool

T0 = datetime(2024, 5, 6, 10, 0, tzinfo=timezone.utc)
TIMEOUT = 10


class Recorder:
    def __init__(self):
        self.jobs = []

    def notify(self, job):
        self.jobs.append((job.id, job.state))


def build():
    clock = FrozenClock(T0)
    producer = JobQueue(MemoryJobStore(), clock=clock)  # producers do not know the worker's handlers
    registry = HandlerRegistry()
    registry.register("resize", lambda payload: "resized")
    notifier, history = Recorder(), ExecutionHistory()
    executor = Executor(producer.store, registry, clock=clock, notifier=notifier, history=history)
    pool = WorkerPool(producer, executor, size=1, poll_interval=0.05)
    return clock, producer, pool, notifier, history


def run_until_settled(clock, pool, queue, job_id, rounds=40):
    for _ in range(rounds):
        pool.drain()
        assert queue.get(job_id).state != JobState.RUNNING, "job left RUNNING after the worker gave up on it"
        if queue.get(job_id).state.is_terminal:
            return queue.get(job_id)
        clock.advance(hours=12)
    raise AssertionError("job never reached a final state")


def test_job_with_unknown_handler_fails():
    clock, queue, pool, notifier, history = build()
    job = queue.enqueue("thumbnail", {"src": "a.png"}, unique_key="thumb-a")
    final = run_until_settled(clock, pool, queue, job.id)
    assert final.state == JobState.FAILED
    assert final.finished_at is not None and "thumbnail" in final.last_error
    assert (job.id, JobState.FAILED) in notifier.jobs
    attempts = history.attempts(job.id)
    assert attempts and attempts[-1].outcome == "failed" and "thumbnail" in attempts[-1].error
    assert queue.store.find_active("thumb-a") is None
    assert queue.enqueue("thumbnail", unique_key="thumb-a").id != job.id


def test_other_jobs_keep_running():
    clock, queue, pool, notifier, history = build()
    missing = queue.enqueue("thumbnail", priority=9)
    after = [queue.enqueue("resize", {"n": n}) for n in range(3)]
    pool.drain()
    assert queue.get(missing.id).state != JobState.RUNNING
    assert [queue.get(job.id).state for job in after] == [JobState.SUCCEEDED] * 3


def test_worker_threads_handle_unknown_handlers():
    clock, queue, pool, notifier, history = build()
    done = threading.Event()
    seen = []
    pool.on_job_done.append(lambda job: (seen.append(job.id), len(seen) >= 2 and done.set()))
    pool.start()
    try:
        missing = queue.enqueue("thumbnail", max_attempts=1)
        ok = queue.enqueue("resize")
        assert done.wait(TIMEOUT)
    finally:
        assert pool.stop(timeout=TIMEOUT)
    assert queue.get(missing.id).state == JobState.FAILED
    assert queue.get(ok.id).state == JobState.SUCCEEDED
