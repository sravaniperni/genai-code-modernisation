import threading

import pytest

from jobqueue.executor import Executor
from jobqueue.job import JobState
from jobqueue.workers import WorkerPool

TIMEOUT = 10


@pytest.fixture
def pool(queue):
    pool = WorkerPool(queue, Executor(queue.store, queue.registry, clock=queue.clock), size=2, poll_interval=0.05)
    yield pool
    pool.stop(timeout=TIMEOUT)


def wait_for_jobs(pool, count):
    done, finished = threading.Event(), []

    def collect(job):
        finished.append(job)
        if len(finished) >= count:
            done.set()

    pool.on_job_done.append(collect)
    return done, finished


def test_threads_process_queued_jobs(queue, pool):
    done, finished = wait_for_jobs(pool, 4)
    pool.start()
    assert pool.running and len(pool.worker_names()) == 2
    jobs = [queue.enqueue("add", {"a": n, "b": n}) for n in range(4)]
    assert done.wait(TIMEOUT)
    assert sorted(queue.get(job.id).result for job in jobs) == [0, 2, 4, 6]
    assert {job.worker for job in finished} <= set(pool.worker_names())
    assert pool.stop(timeout=TIMEOUT) and not pool.running


def test_idle_workers_wake_up_when_a_job_arrives(queue):
    pool = WorkerPool(queue, Executor(queue.store, queue.registry, clock=queue.clock), size=1, poll_interval=60)
    done, _ = wait_for_jobs(pool, 1)
    pool.start()
    try:
        queue.enqueue("add", {"a": 1, "b": 1})
        assert done.wait(TIMEOUT)
    finally:
        assert pool.stop(timeout=TIMEOUT)


def test_stop_lets_the_running_job_finish(queue, pool):
    started, release = threading.Event(), threading.Event()

    def slow(payload):
        started.set()
        release.wait(TIMEOUT)
        return "finished"

    queue.registry.register("slow", slow)
    pool.start()
    job = queue.enqueue("slow")
    assert started.wait(TIMEOUT)
    assert pool.stop(timeout=0.01) is False
    release.set()
    assert pool.stop(timeout=TIMEOUT) is True
    assert queue.get(job.id).state == JobState.SUCCEEDED


def test_inline_draining(queue, pool):
    for n in range(3):
        queue.enqueue("add", {"a": n, "b": 0}, priority=n)
    assert pool.run_once().result == 2
    assert pool.drain() == 2 and pool.run_once() is None
