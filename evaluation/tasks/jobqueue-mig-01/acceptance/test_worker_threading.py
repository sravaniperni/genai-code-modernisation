import os
import re
import threading
from pathlib import Path

from jobqueue.executor import Executor
from jobqueue.job import JobState
from jobqueue.queue import JobQueue
from jobqueue.registry import HandlerRegistry
from jobqueue.workers import WorkerPool

TIMEOUT = 10


def make_pool(size=3, name="imgworker"):
    registry = HandlerRegistry()
    registry.register("tag", lambda payload: threading.current_thread().name)
    queue = JobQueue(registry=registry)
    pool = WorkerPool(queue, Executor(queue.store, registry), size=size, poll_interval=0.05, name=name)
    return queue, pool


def test_workers_are_named_daemon_threads():
    queue, pool = make_pool()
    pool.start()
    try:
        assert pool.worker_names() == ["imgworker-1", "imgworker-2", "imgworker-3"]
        threads = {thread.name: thread for thread in threading.enumerate()}
        for name in pool.worker_names():
            assert threads[name].daemon and threads[name].is_alive()
    finally:
        assert pool.stop(timeout=TIMEOUT)
    assert pool.worker_names() == []
    assert not any(t.name.startswith("imgworker-") for t in threading.enumerate())


def test_jobs_record_their_worker_thread():
    queue, pool = make_pool(size=2, name="tagger")
    done = threading.Event()
    finished = []

    def collect(job):
        finished.append(job)
        if len(finished) == 6:
            done.set()

    pool.on_job_done.append(collect)
    pool.start()
    try:
        jobs = [queue.enqueue("tag") for _ in range(6)]
        assert done.wait(TIMEOUT)
        names = set(pool.worker_names())
    finally:
        assert pool.stop(timeout=TIMEOUT)
    for job in jobs:
        stored = queue.get(job.id)
        assert stored.state == JobState.SUCCEEDED
        assert stored.worker in names and stored.result == stored.worker


def test_pool_can_be_restarted():
    queue, pool = make_pool(size=1, name="again")
    for _ in range(2):
        pool.start()
        assert pool.worker_names() == ["again-1"]
        assert pool.stop(timeout=TIMEOUT)


def test_deprecated_aliases_are_gone():
    source = (Path(os.environ["REPO_ROOT"]) / "src" / "jobqueue" / "workers.py").read_text()
    assert not re.search(r"\.(setDaemon|getName|isDaemon|setName)\(|currentThread\(", source)
