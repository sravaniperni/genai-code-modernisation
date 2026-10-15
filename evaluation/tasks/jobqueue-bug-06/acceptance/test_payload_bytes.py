import json

import pytest

from jobqueue.errors import PayloadTooLarge
from jobqueue.payload import check_payload_size, encode_payload, payload_size
from jobqueue.queue import JobQueue
from jobqueue.registry import HandlerRegistry
from jobqueue.spec import PayloadSchema


def stored_bytes(payload):
    return len(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))


@pytest.mark.parametrize("payload", [
    {"city": "Zürich"},
    {"note": "€" * 10},
    {"greeting": "こんにちは", "lang": "ja"},
    {"emoji": "🎉🚀", "n": 1},
    {"ascii": "plain text"},
])
def test_payload_size_counts_utf8_bytes(payload):
    assert payload_size(payload) == stored_bytes(payload)
    assert payload_size(payload) == len(encode_payload(payload).encode("utf-8"))


def test_zurich_example():
    assert payload_size({"city": "Zürich"}) == 18


def test_limit_is_enforced_in_bytes():
    payload = {"note": "€" * 600}
    with pytest.raises(PayloadTooLarge) as info:
        check_payload_size(payload, limit=1024)
    assert info.value.size == stored_bytes(payload) and info.value.limit == 1024


def test_exact_limit_is_allowed():
    payload = {"t": "ü" * 50}
    size = stored_bytes(payload)
    assert check_payload_size(payload, limit=size) == size
    with pytest.raises(PayloadTooLarge):
        check_payload_size(payload, limit=size - 1)


def test_queue_rejects_oversized_non_ascii_payloads():
    queue = JobQueue(max_payload_bytes=1024)
    with pytest.raises(PayloadTooLarge):
        queue.enqueue("note", {"note": "€" * 600})
    assert queue.store.list() == []
    accepted = queue.enqueue("note", {"note": "e" * 600})
    assert queue.get(accepted.id).payload == {"note": "e" * 600}


class Message(PayloadSchema):
    body: str
    channel: str = "#général"


def test_queue_measures_the_normalised_payload():
    registry = HandlerRegistry()
    registry.register("post", lambda payload: None, schema=Message)
    limit = stored_bytes({"body": "ok", "channel": "#général"})
    queue = JobQueue(registry=registry, max_payload_bytes=limit)
    assert queue.enqueue("post", {"body": "ok"}).payload == {"body": "ok", "channel": "#général"}
    with pytest.raises(PayloadTooLarge):
        queue.enqueue("post", {"body": "oké"})
