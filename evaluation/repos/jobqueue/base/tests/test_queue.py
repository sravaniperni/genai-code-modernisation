from datetime import timedelta

import pytest

from jobqueue.errors import DuplicateJob, HandlerNotFound, InvalidJobSpec, PayloadTooLarge
from jobqueue.job import JobState
from jobqueue.queue import JobQueue
from jobqueue.spec import PayloadSchema

from conftest import START


def test_enqueue_stores_a_pending_job(queue):
    job = queue.enqueue("add", {"a": 1, "b": 2}, priority=8, queue="math")
    stored = queue.get(job.id)
    assert (stored.state, stored.priority, stored.queue, stored.attempts) == (JobState.PENDING, 8, "math", 0)
    assert stored.created_at == START and stored.run_at is None


def test_delay_postpones_the_job(queue):
    job = queue.enqueue("add", {"a": 1, "b": 2}, delay=90)
    assert job.run_at == START + timedelta(seconds=90)
    assert queue.store.claim_next(START, "w") is None


def test_submissions_are_validated(queue):
    with pytest.raises(HandlerNotFound):
        queue.enqueue("missing")
    with pytest.raises(InvalidJobSpec):
        queue.enqueue("add", priority=-1)
    small = JobQueue(registry=queue.registry, max_payload_bytes=32)
    with pytest.raises(PayloadTooLarge):
        small.enqueue("add", {"a": "x" * 40, "b": ""})


class Thumbnail(PayloadSchema):
    url: str
    size: int = 128


def test_payload_schema_applied(queue):
    queue.registry.register("thumbnail", lambda payload: None, schema=Thumbnail)
    assert queue.enqueue("thumbnail", {"url": "s3://bucket/a.png"}).payload == {"url": "s3://bucket/a.png", "size": 128}
    with pytest.raises(InvalidJobSpec):
        queue.enqueue("thumbnail", {"size": 64})


def test_unique_key_blocks_duplicates_while_active(queue):
    job = queue.enqueue("add", {"a": 1, "b": 1}, unique_key="nightly")
    with pytest.raises(DuplicateJob) as info:
        queue.enqueue("add", {"a": 1, "b": 1}, unique_key="nightly")
    assert info.value.existing_id == job.id
    job.state = JobState.SUCCEEDED
    queue.store.update(job)
    assert queue.enqueue("add", {"a": 1, "b": 1}, unique_key="nightly").id != job.id


def test_listeners_hear_about_new_jobs(queue):
    seen = []
    queue.listeners.append(seen.append)
    job = queue.enqueue("add", {"a": 1, "b": 1})
    assert [item.id for item in seen] == [job.id]
