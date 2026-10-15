import importlib.metadata
import json
from datetime import datetime, timedelta, timezone

import pytest
from click.testing import CliRunner

from jobqueue.cli import AdminContext, cli
from jobqueue.errors import SerializationError
from jobqueue.job import Job, JobState
from jobqueue.serialization import dump_jobs, load_jobs
from jobqueue.sqlstore import SQLJobStore

T0 = datetime(2024, 5, 6, 8, 30, 15, 250000, tzinfo=timezone.utc)
FIELDS = ("id", "name", "queue", "state", "priority", "payload", "attempts", "max_attempts", "run_at",
          "created_at", "finished_at", "last_error", "unique_key")


def job(**kwargs):
    defaults = dict(name="invoice", payload={"number": 7, "email": "a@example.test"}, queue="billing", priority=7,
                    state=JobState.SUCCEEDED, attempts=2, max_attempts=4, created_at=T0,
                    run_at=T0 + timedelta(minutes=1), finished_at=T0 + timedelta(minutes=2), last_error=None,
                    unique_key="inv-7")
    return Job(**{**defaults, **kwargs})


def test_marshmallow_version_is_pinned():
    assert importlib.metadata.version("marshmallow") == "4.0.1"


def test_dump_document_format():
    data = json.loads(dump_jobs([job(), job(name="other", run_at=None)]))
    assert data["version"] == 1 and len(data["jobs"]) == 2
    record = data["jobs"][0]
    assert record["created_at"] == "2024-05-06T08:30:15.250000+00:00"
    assert record["state"] == "succeeded" and record["payload"] == {"number": 7, "email": "a@example.test"}
    assert data["jobs"][1]["run_at"] is None


def test_round_trip_preserves_fields():
    original = [job(), job(state=JobState.FAILED, last_error="boom", unique_key=None)]
    loaded = load_jobs(dump_jobs(original))
    for before, after in zip(original, loaded):
        assert isinstance(after, Job)
        for field in FIELDS:
            assert getattr(after, field) == getattr(before, field), field
    assert loaded[0].created_at.utcoffset() == timedelta(0)


def test_redaction_is_opt_in():
    assert json.loads(dump_jobs([job()]))["jobs"][0]["payload"]["email"] == "a@example.test"
    redacted = json.loads(dump_jobs([job()], redact_payload=True))["jobs"][0]["payload"]
    assert redacted == {"number": "***", "email": "***"}


def test_bare_lists_defaults_and_time_zones():
    records = [{"id": "a", "name": "x", "created_at": "2024-05-06T10:00:00"},
               {"id": "b", "name": "y", "created_at": "2024-05-06T12:00:00+02:00", "unknown": "ignored"}]
    first, second = load_jobs(json.dumps(records))
    assert (first.state, first.queue, first.priority, first.payload, first.attempts) == (
        JobState.PENDING, "default", 5, {}, 0)
    assert first.created_at == datetime(2024, 5, 6, 10, 0, tzinfo=timezone.utc)
    assert second.created_at == datetime(2024, 5, 6, 10, 0, tzinfo=timezone.utc)
    assert second.created_at.utcoffset() == timedelta(0)


def test_errors_are_reported_per_field():
    bad = {"version": 1, "jobs": [
        {"id": "a", "name": "   ", "created_at": "2024-05-06T10:00:00Z"},
        {"id": "b", "name": "y", "created_at": "not a date", "state": "exploded"},
    ]}
    with pytest.raises(SerializationError) as info:
        load_jobs(json.dumps(bad))
    messages = info.value.messages
    assert set(messages[0]) == {"name"} and set(messages[1]) == {"created_at", "state"}
    with pytest.raises(SerializationError) as info:
        load_jobs(json.dumps({"version": 2, "jobs": []}))
    assert "version" in info.value.messages
    with pytest.raises(SerializationError):
        load_jobs("[{]")


def test_cli_export_redacts():
    store = SQLJobStore("sqlite://")
    store.add(job())
    result = CliRunner().invoke(cli, ["export", "--redact"], obj=AdminContext(store=store))
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["jobs"][0]["payload"] == {"number": "***", "email": "***"}
