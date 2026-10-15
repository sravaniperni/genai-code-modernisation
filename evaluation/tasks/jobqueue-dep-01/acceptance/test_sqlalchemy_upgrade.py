import importlib.metadata
import threading
from datetime import datetime, timedelta, timezone

import pytest
from click.testing import CliRunner
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from jobqueue.cli import cli
from jobqueue.errors import JobNotFound
from jobqueue.job import Job, JobState
from jobqueue.sqlstore import JobRecord, SQLJobStore

T0 = datetime(2024, 5, 6, 8, 0, 0, tzinfo=timezone.utc)


def make(**kwargs):
    kwargs.setdefault("created_at", T0)
    return Job(name=kwargs.pop("name", "resize"), payload=kwargs.pop("payload", {"w": 640, "label": "Zürich"}),
               **kwargs)


def test_sqlalchemy_version_is_pinned():
    assert importlib.metadata.version("SQLAlchemy") == "2.0.36"


def test_add_get_update_round_trip():
    store = SQLJobStore("sqlite://")
    job = make(priority=7, queue="media", run_at=T0 + timedelta(minutes=3), unique_key="img-1")
    store.add(job)
    assert store.get(job.id) == job
    job.state, job.result, job.last_error = JobState.FAILED, {"pixels": [1, 2]}, "boom"
    job.finished_at = T0 + timedelta(seconds=9, microseconds=250)
    store.update(job)
    loaded = store.get(job.id)
    assert loaded == job and loaded.finished_at.utcoffset() == timedelta(0)
    with pytest.raises(JobNotFound):
        store.get("nope")
    with pytest.raises(JobNotFound):
        store.update(make())


def test_claim_order_and_filters():
    store = SQLJobStore("sqlite://")
    low = make(priority=1)
    first = make(priority=5, created_at=T0 + timedelta(seconds=1))
    second = make(priority=5, created_at=T0 + timedelta(seconds=2))
    urgent = make(priority=9, created_at=T0 + timedelta(seconds=3))
    later = make(priority=9, run_at=T0 + timedelta(hours=1))
    other = make(priority=9, queue="emails")
    for job in (low, first, second, urgent, later, other):
        store.add(job)
    now = T0 + timedelta(minutes=1)
    order = [store.claim_next(now, "w", queues=["default"]) for _ in range(5)]
    assert [job.id if job else None for job in order] == [urgent.id, first.id, second.id, low.id, None]
    claimed = store.get(urgent.id)
    assert (claimed.state, claimed.attempts, claimed.worker, claimed.started_at) == (JobState.RUNNING, 1, "w", now)
    assert store.claim_next(now, "w").id == other.id
    assert store.claim_next(T0 + timedelta(hours=2), "w").id == later.id


def test_listing_counting_and_unique_keys():
    store = SQLJobStore("sqlite://")
    jobs = [make(queue=q, unique_key=f"k{n}", created_at=T0 + timedelta(seconds=n)) for n, q in
            enumerate(["a", "b", "a"])]
    for job in jobs:
        store.add(job)
    jobs[1].state = JobState.SUCCEEDED
    store.update(jobs[1])
    assert [job.id for job in store.list()] == [job.id for job in jobs]
    assert [job.id for job in store.list(queue="a", limit=1)] == [jobs[0].id]
    assert [job.id for job in store.list(state=JobState.SUCCEEDED)] == [jobs[1].id]
    assert store.counts() == {"pending": 2, "running": 0, "succeeded": 1, "failed": 0, "cancelled": 0}
    assert store.queues() == ["a", "b"]
    assert store.find_active("k0").id == jobs[0].id
    assert store.find_active("k1") is None and store.find_active("missing") is None


def test_changes_are_committed_to_the_database_file(tmp_path):
    url = f"sqlite:///{tmp_path / 'jobs.db'}"
    writer = SQLJobStore(url)
    job = make()
    writer.add(job)
    claimed = writer.claim_next(T0, "w1")
    claimed.state, claimed.result = JobState.SUCCEEDED, 42
    writer.update(claimed)
    writer.add(make(name="second"))
    writer.close()
    reader = SQLJobStore(url)
    assert reader.get(job.id).state == JobState.SUCCEEDED and reader.get(job.id).result == 42
    assert [j.name for j in reader.list()] == ["resize", "second"]
    assert reader.claim_next(T0, "w2").name == "second"
    reader.close()
    assert SQLJobStore(url).counts()["running"] == 1


def test_concurrent_claims_hand_out_each_job_once(tmp_path):
    store = SQLJobStore(f"sqlite:///{tmp_path / 'jobs.db'}")
    for n in range(40):
        store.add(make(created_at=T0 + timedelta(seconds=n)))
    claimed, errors = [], []

    def worker(name):
        try:
            while (job := store.claim_next(T0 + timedelta(hours=1), name)) is not None:
                claimed.append(job.id)
        except Exception as exc:  # pragma: no cover - reported below
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(f"w{n}",)) for n in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
    assert errors == []
    assert len(claimed) == 40 and len(set(claimed)) == 40
    assert store.counts()["running"] == 40


def test_explicit_engine_and_orm_mapping():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    store = SQLJobStore(engine=engine)
    job = make(priority=3)
    store.add(job)
    with Session(engine) as session:
        record = session.get(JobRecord, job.id)
        assert (record.name, record.priority, record.state) == ("resize", 3, "pending")
    assert JobRecord.__table__.name == "jobqueue_jobs"


def test_cli_against_a_database_file(tmp_path):
    url = f"sqlite:///{tmp_path / 'admin.db'}"
    runner = CliRunner()
    created = runner.invoke(cli, ["--db", url, "enqueue", "resize", "--payload", '{"w": 1}', "--queue", "media"])
    assert created.exit_code == 0, created.output
    listing = runner.invoke(cli, ["--db", url, "list", "--queue", "media"], env={"COLUMNS": "120"})
    assert listing.exit_code == 0 and created.output.strip()[:12] in listing.output
    assert SQLJobStore(url).get(created.output.strip()).payload == {"w": 1}
