import importlib.metadata
from datetime import datetime, timedelta, timezone

import pytest

from jobqueue.errors import InvalidJobSpec
from jobqueue.queue import JobQueue
from jobqueue.registry import HandlerRegistry
from jobqueue.spec import PayloadSchema, parse_spec, validate_payload


def errors_for(data):
    with pytest.raises(InvalidJobSpec) as info:
        parse_spec(data)
    return info.value.errors


def test_pydantic_version_is_pinned():
    assert importlib.metadata.version("pydantic") == "2.9.2"


def test_optional_fields_keep_their_defaults():
    spec = parse_spec({"name": "send-mail"})
    assert spec.run_at is None and spec.unique_key is None
    assert (spec.queue, spec.priority, spec.max_attempts, spec.delay, spec.payload) == ("default", 5, 3, 0.0, {})


def test_errors_are_keyed_by_field():
    assert "priority" in errors_for({"name": "x", "priority": 10})
    assert "max_attempts" in errors_for({"name": "x", "max_attempts": 26})
    assert "queue" in errors_for({"name": "x", "queue": "9lives"})
    assert "delay" in errors_for({"name": "x", "delay": -1})
    assert "unique_key" in errors_for({"name": "x", "unique_key": ""})
    assert "name" in errors_for({"name": "x" * 121})
    assert "retries" in errors_for({"name": "x", "retries": 3})
    assert set(errors_for({"name": "", "priority": -1})) >= {"name", "priority"}


def test_delay_and_run_at_are_mutually_exclusive():
    run_at = datetime(2024, 5, 6, 12, 0, tzinfo=timezone.utc)
    with pytest.raises(InvalidJobSpec):
        parse_spec({"name": "x", "delay": 30, "run_at": run_at})
    assert parse_spec({"name": "x", "delay": 0, "run_at": run_at}).run_at == run_at


def test_run_at_is_normalised_to_utc():
    tokyo = timezone(timedelta(hours=9))
    spec = parse_spec({"name": "x", "run_at": datetime(2024, 5, 6, 21, 0, tzinfo=tokyo)})
    assert spec.run_at == datetime(2024, 5, 6, 12, 0, tzinfo=timezone.utc)
    assert spec.run_at.utcoffset() == timedelta(0)
    assert "run_at" in errors_for({"name": "x", "run_at": datetime(2024, 5, 6, 12, 0)})


def test_strings_are_stripped():
    spec = parse_spec({"name": "  send-mail\n", "queue": " emails ", "unique_key": " order-7 "})
    assert (spec.name, spec.queue, spec.unique_key) == ("send-mail", "emails", "order-7")


def test_specs_are_immutable():
    spec = parse_spec({"name": "send-mail", "priority": 2})
    with pytest.raises((TypeError, ValueError)):
        spec.priority = 9
    assert spec.priority == 2


class Invoice(PayloadSchema):
    number: int
    currency: str = "EUR"
    lines: list = []


def test_payload_schemas():
    assert validate_payload(Invoice, {"number": "17"}) == {"number": 17, "currency": "EUR", "lines": []}
    with pytest.raises(InvalidJobSpec) as info:
        validate_payload(Invoice, {"currency": "USD", "discount": 5})
    assert set(info.value.errors) == {"payload.number", "payload.discount"}


def test_queue_applies_schema_and_spec():
    registry = HandlerRegistry()
    registry.register("invoice", lambda payload: None, schema=Invoice)
    queue = JobQueue(registry=registry)
    job = queue.enqueue("invoice", {"number": 3}, priority="7", queue="billing")
    assert (job.payload, job.priority, job.queue, job.run_at) == ({"number": 3, "currency": "EUR", "lines": []}, 7,
                                                                  "billing", None)
    with pytest.raises(InvalidJobSpec) as info:
        queue.enqueue("invoice", {"number": 3, "rush": True})
    assert "payload.rush" in info.value.errors
