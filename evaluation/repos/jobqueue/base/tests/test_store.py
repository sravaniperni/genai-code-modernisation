from datetime import timedelta

import pytest

from jobqueue.errors import JobNotFound
from jobqueue.job import Job, JobState
from jobqueue.sqlstore import SQLJobStore
from jobqueue.store import MemoryJobStore

from conftest import START


@pytest.fixture(params=["memory", "sql"])
def store(request):
    store = MemoryJobStore() if request.param == "memory" else SQLJobStore("sqlite://")
    yield store
    store.close()


def make(name="add", **kwargs):
    kwargs.setdefault("created_at", START)
    return Job(name=name, payload={"a": 1, "b": 2}, **kwargs)


def test_round_trip_preserves_fields(store):
    job = make(priority=8, queue="emails", run_at=START + timedelta(minutes=5), unique_key="k1")
    store.add(job)
    loaded = store.get(job.id)
    assert loaded == job
    assert loaded.run_at.tzinfo is not None and loaded.run_at == START + timedelta(minutes=5)
    with pytest.raises(JobNotFound):
        store.get("missing")


def test_claim_prefers_higher_priority(store):
    low, high, normal = make(priority=1), make(priority=9), make(priority=5)
    for job in (low, high, normal):
        store.add(job)
    claimed = [store.claim_next(START, "w1").id for _ in range(3)]
    assert claimed == [high.id, normal.id, low.id]
    assert store.claim_next(START, "w1") is None
    running = store.get(high.id)
    assert (running.state, running.attempts, running.worker, running.started_at) == (JobState.RUNNING, 1, "w1", START)


def test_claim_skips_future_jobs_and_other_queues(store):
    later = make(run_at=START + timedelta(minutes=1))
    other = make(queue="emails")
    store.add(later)
    store.add(other)
    assert store.claim_next(START, "w1", queues=["default"]) is None
    assert store.claim_next(START + timedelta(minutes=1), "w1", queues=["default"]).id == later.id
    assert store.claim_next(START, "w1").id == other.id


def test_update_counts_and_filters(store):
    first, second = make(queue="emails"), make()
    store.add(first)
    store.add(second)
    first.state, first.result = JobState.SUCCEEDED, {"ok": True}
    store.update(first)
    assert store.get(first.id).result == {"ok": True}
    assert store.counts()["succeeded"] == 1 and store.counts()["pending"] == 1
    assert [job.id for job in store.list()] == [first.id, second.id]
    assert [job.id for job in store.list(state=JobState.PENDING)] == [second.id]
    assert [job.id for job in store.list(queue="emails")] == [first.id]
    assert store.queues() == ["default", "emails"]


def test_find_active_by_unique_key(store):
    job = make(unique_key="invoice-42")
    store.add(job)
    assert store.find_active("invoice-42").id == job.id
    job.state = JobState.SUCCEEDED
    store.update(job)
    assert store.find_active("invoice-42") is None


def test_memory_store_claims_equal_priority_in_submission_order():
    store = MemoryJobStore()
    jobs = [make(created_at=START + timedelta(seconds=n)) for n in range(3)]
    for job in jobs:
        store.add(job)
    assert [store.claim_next(START + timedelta(minutes=1), "w").id for _ in jobs] == [job.id for job in jobs]
