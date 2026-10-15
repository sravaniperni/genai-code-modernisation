import json
from datetime import timedelta

import pytest

from jobqueue.errors import SerializationError
from jobqueue.job import Job, JobState
from jobqueue.serialization import dump_jobs, load_jobs

from conftest import START


def sample():
    return Job(name="add", payload={"a": 1, "b": 2}, queue="math", priority=8, state=JobState.FAILED, attempts=3,
               created_at=START, run_at=START + timedelta(minutes=5), last_error="boom", unique_key="k")


def test_round_trip():
    job = sample()
    data = json.loads(dump_jobs([job]))
    assert data["version"] == 1 and data["jobs"][0]["created_at"] == "2024-03-01T09:59:30+00:00"
    [loaded] = load_jobs(dump_jobs([job]))
    for field in ("id", "name", "payload", "queue", "priority", "state", "attempts", "created_at", "run_at",
                  "last_error", "unique_key"):
        assert getattr(loaded, field) == getattr(job, field)


def test_payload_redaction():
    data = json.loads(dump_jobs([sample()], redact_payload=True))
    assert data["jobs"][0]["payload"] == {"a": "***", "b": "***"}


def test_bare_lists_and_defaults_are_accepted():
    [job] = load_jobs(json.dumps([{"id": "j1", "name": "add", "created_at": "2024-03-01T10:00:00"}]))
    assert (job.state, job.queue, job.priority, job.payload) == (JobState.PENDING, "default", 5, {})
    assert job.created_at.utcoffset() == timedelta(0)


def test_invalid_records_are_reported():
    with pytest.raises(SerializationError) as info:
        load_jobs(json.dumps({"version": 1, "jobs": [{"id": "j1", "name": " ", "created_at": "yesterday"}]}))
    assert set(info.value.messages[0]) == {"name", "created_at"}
    with pytest.raises(SerializationError):
        load_jobs("{not json")
