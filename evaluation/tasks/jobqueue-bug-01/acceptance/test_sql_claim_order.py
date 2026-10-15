import random
from datetime import datetime, timedelta, timezone

from jobqueue.clock import FrozenClock
from jobqueue.executor import Executor
from jobqueue.job import Job
from jobqueue.queue import JobQueue
from jobqueue.registry import HandlerRegistry
from jobqueue.sqlstore import SQLJobStore
from jobqueue.store import MemoryJobStore
from jobqueue.workers import WorkerPool

T0 = datetime(2024, 5, 6, 10, 0, tzinfo=timezone.utc)


def claim_all(store, now, queues=None):
    order = []
    while (job := store.claim_next(now, "w", queues)) is not None:
        order.append(job.name)
    return order


def test_equal_priority_jobs_are_claimed_oldest_first():
    store = SQLJobStore("sqlite://")
    for n, name in enumerate(["report-a", "report-b", "report-c"]):
        store.add(Job(name=name, created_at=T0 + timedelta(seconds=5 * n)))
    assert claim_all(store, T0 + timedelta(minutes=1)) == ["report-a", "report-b", "report-c"]


def test_same_instant_keeps_submission_order():
    store = SQLJobStore("sqlite://")
    for name in ["first", "second", "third", "fourth"]:
        store.add(Job(name=name, created_at=T0))
    assert claim_all(store, T0) == ["first", "second", "third", "fourth"]


def test_priority_still_wins_over_age():
    store = SQLJobStore("sqlite://")
    specs = [("old-low", 1, 0), ("old-high", 8, 1), ("new-high", 8, 2), ("new-low", 1, 3), ("mid", 5, 4)]
    for name, priority, offset in specs:
        store.add(Job(name=name, priority=priority, created_at=T0 + timedelta(seconds=offset)))
    assert claim_all(store, T0 + timedelta(minutes=1)) == ["old-high", "new-high", "mid", "old-low", "new-low"]


def test_due_jobs_and_queue_filters_follow_the_same_order():
    store = SQLJobStore("sqlite://")
    store.add(Job(name="delayed-old", created_at=T0, run_at=T0 + timedelta(minutes=10)))
    store.add(Job(name="ready-new", created_at=T0 + timedelta(minutes=1)))
    store.add(Job(name="mail-old", queue="mail", created_at=T0 + timedelta(minutes=2)))
    store.add(Job(name="mail-new", queue="mail", created_at=T0 + timedelta(minutes=3)))
    assert claim_all(store, T0 + timedelta(minutes=5), queues=["default"]) == ["ready-new"]
    store.add(Job(name="ready-newest", created_at=T0 + timedelta(minutes=4)))
    assert claim_all(store, T0 + timedelta(minutes=10), queues=["default"]) == ["delayed-old", "ready-newest"]
    assert claim_all(store, T0 + timedelta(minutes=10), queues=["mail"]) == ["mail-old", "mail-new"]


def test_sql_and_memory_stores_agree():
    rng = random.Random(20240506)
    memory, sql = MemoryJobStore(), SQLJobStore("sqlite://")
    for n in range(60):
        job = Job(name=f"job-{n}", priority=rng.choice([1, 5, 5, 8]),
                  created_at=T0 + timedelta(seconds=rng.choice([0, 1, 2, 3])))
        memory.add(job)
        sql.add(job)
    now = T0 + timedelta(hours=1)
    assert claim_all(sql, now) == claim_all(memory, now)


def test_workers_execute_in_submission_order():
    clock = FrozenClock(T0)
    registry = HandlerRegistry()
    executed = []
    registry.register("record", lambda payload: executed.append(payload["n"]))
    queue = JobQueue(SQLJobStore("sqlite://"), registry=registry, clock=clock)
    for n in range(5):
        queue.enqueue("record", {"n": n})
        clock.advance(seconds=1)
    pool = WorkerPool(queue, Executor(queue.store, registry, clock=clock), size=1)
    assert pool.drain() == 5
    assert executed == [0, 1, 2, 3, 4]
