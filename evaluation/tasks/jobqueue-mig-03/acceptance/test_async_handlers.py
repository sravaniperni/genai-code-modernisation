import asyncio
import inspect
import os
import re
import threading
from pathlib import Path

import pytest

from jobqueue.aio import run_coroutine, run_handler
from jobqueue.executor import Executor
from jobqueue.job import JobState
from jobqueue.queue import JobQueue
from jobqueue.registry import HandlerRegistry
from jobqueue.workers import WorkerPool

TIMEOUT = 10


@pytest.fixture(autouse=True)
def fresh_event_loop_policy():
    # Behave like a freshly started process: no event loop has been created or set yet.
    asyncio.set_event_loop_policy(None)
    yield
    asyncio.set_event_loop_policy(None)


async def scaled(payload):
    await asyncio.sleep(0)
    return payload["n"] * 10


def test_run_coroutine_in_the_main_thread():
    assert run_coroutine(scaled({"n": 1})) == 10
    assert run_coroutine(scaled({"n": 2})) == 20
    assert run_handler(scaled, {"n": 3}) == 30
    assert asyncio.run(scaled({"n": 4})) == 40


def test_run_coroutine_in_concurrent_worker_threads():
    barrier = threading.Barrier(3)
    results, errors = {}, []

    def work(n):
        try:
            barrier.wait(TIMEOUT)
            results[n] = run_coroutine(scaled({"n": n}))
        except Exception as exc:  # pragma: no cover - reported below
            errors.append(exc)

    threads = [threading.Thread(target=work, args=(n,)) for n in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(TIMEOUT)
    assert errors == [] and results == {0: 0, 1: 10, 2: 20}


def test_nesting_inside_a_running_loop_is_refused():
    async def outer():
        inner = scaled({"n": 1})
        with pytest.raises(RuntimeError):
            run_coroutine(inner)
        assert inspect.getcoroutinestate(inner) == inspect.CORO_CLOSED
        return "ok"

    assert asyncio.run(outer()) == "ok"


def test_executor_and_pool_run_async_handlers():
    registry = HandlerRegistry()
    registry.register("scaled", scaled)
    queue = JobQueue(registry=registry)
    inline = queue.enqueue("scaled", {"n": 5})
    Executor(queue.store, registry).execute(queue.store.claim_next(queue.clock.now(), "main"))
    assert queue.get(inline.id).result == 50

    pool = WorkerPool(queue, Executor(queue.store, registry), size=2, poll_interval=0.05)
    done = threading.Event()
    finished = []
    pool.on_job_done.append(lambda job: (finished.append(job), len(finished) == 4 and done.set()))
    pool.start()
    try:
        jobs = [queue.enqueue("scaled", {"n": n}) for n in range(4)]
        assert done.wait(TIMEOUT)
    finally:
        assert pool.stop(timeout=TIMEOUT)
    assert all(queue.get(job.id).state == JobState.SUCCEEDED for job in jobs)
    assert sorted(queue.get(job.id).result for job in jobs) == [0, 10, 20, 30]


def test_get_event_loop_is_no_longer_used():
    source = (Path(os.environ["REPO_ROOT"]) / "src" / "jobqueue" / "aio.py").read_text()
    assert not re.search(r"\bget_event_loop\(", source)
