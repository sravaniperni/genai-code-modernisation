from datetime import timedelta

from jobqueue.history import ExecutionHistory
from jobqueue.job import Job

from conftest import START


def test_attempts_are_returned_in_order_with_utc_times():
    history = ExecutionHistory()
    job = Job(name="add", attempts=1)
    history.record(job, "retrying", START, START + timedelta(seconds=2, microseconds=500), "boom")
    job.attempts = 2
    history.record(job, "succeeded", START + timedelta(minutes=1), START + timedelta(minutes=1, seconds=1))
    first, second = history.attempts(job.id)
    assert (first.attempt, first.outcome, first.error) == (1, "retrying", "boom")
    assert first.finished_at == START + timedelta(seconds=2, microseconds=500)
    assert second.started_at.utcoffset() == timedelta(0) and second.outcome == "succeeded"
    assert history.attempts("other") == []


def test_history_survives_reopening(tmp_path):
    path = str(tmp_path / "history.db")
    history = ExecutionHistory(path)
    history.record(Job(name="add", id="j1", attempts=1), "succeeded", START, START)
    history.close()
    assert ExecutionHistory(path).attempts("j1")[0].finished_at == START
