import os
import re
import threading
import time
from pathlib import Path

from jobqueue.executor import Executor
from jobqueue.job import JobState
from jobqueue.queue import JobQueue
from jobqueue.registry import HandlerRegistry
from jobqueue.workers import WorkerPool

TIMEOUT = 10
SLOW_POLL = 60.0  # workers must be woken explicitly; polling would take a minute


def setup_pool(size=2):
    registry = HandlerRegistry()
    registry.register("echo", lambda payload: payload.get("value"))
    queue = JobQueue(registry=registry)
    pool = WorkerPool(queue, Executor(queue.store, registry), size=size, poll_interval=SLOW_POLL, name="sig")
    return queue, registry, pool


def test_running_reflects_the_lifecycle():
    queue, registry, pool = setup_pool()
    assert pool.running is False
    pool.start()
    assert pool.running is True
    assert pool.stop(timeout=TIMEOUT) is True
    assert pool.running is False


def test_enqueue_wakes_idle_workers():
    queue, registry, pool = setup_pool()
    done = threading.Event()
    pool.on_job_done.append(lambda job: done.set())
    pool.start()
    try:
        job = queue.enqueue("echo", {"value": 7})
        assert done.wait(TIMEOUT), "idle worker was not woken by the new job"
        assert queue.get(job.id).result == 7
    finally:
        assert pool.stop(timeout=TIMEOUT)


def test_stop_wakes_idle_workers_promptly():
    queue, registry, pool = setup_pool(size=3)
    pool.start()
    started = time.monotonic()
    assert pool.stop(timeout=TIMEOUT) is True
    assert time.monotonic() - started < TIMEOUT
    assert not any(t.name.startswith("sig-") for t in threading.enumerate())


def test_stop_is_graceful_with_a_busy_worker():
    queue, registry, pool = setup_pool()
    entered, release = threading.Event(), threading.Event()

    def slow(payload):
        entered.set()
        release.wait(TIMEOUT)
        return "done"

    registry.register("slow", slow)
    pool.start()
    job = queue.enqueue("slow")
    assert entered.wait(TIMEOUT)
    assert pool.stop(timeout=0.05) is False
    assert pool.running is False
    release.set()
    assert pool.stop(timeout=TIMEOUT) is True
    assert queue.get(job.id).state == JobState.SUCCEEDED
    late = queue.enqueue("echo", {"value": 1})
    assert queue.get(late.id).state == JobState.PENDING


def test_deprecated_aliases_are_gone():
    source = (Path(os.environ["REPO_ROOT"]) / "src" / "jobqueue" / "workers.py").read_text()
    assert not re.search(r"\.(isSet|notifyAll)\(", source)
