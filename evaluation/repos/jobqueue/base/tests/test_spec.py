from datetime import datetime, timedelta, timezone

import pytest

from jobqueue.errors import InvalidJobSpec
from jobqueue.spec import PayloadSchema, parse_spec, validate_payload


def test_defaults():
    spec = parse_spec({"name": "resize"})
    assert (spec.queue, spec.priority, spec.max_attempts, spec.delay) == ("default", 5, 3, 0.0)
    assert spec.run_at is None and spec.unique_key is None and spec.payload == {}


def test_field_errors_are_reported_by_field():
    cases = [
        ({"name": "x", "priority": 12}, "priority"),
        ({"name": "x", "queue": "Not A Queue"}, "queue"),
        ({"name": "x", "colour": "red"}, "colour"),
        ({"name": "", "max_attempts": 0}, "max_attempts"),
    ]
    for data, field in cases:
        with pytest.raises(InvalidJobSpec) as info:
            parse_spec(data)
        assert field in info.value.errors


def test_run_at_must_be_aware_and_exclusive_with_delay():
    naive = datetime(2024, 3, 1, 12, 0)
    with pytest.raises(InvalidJobSpec):
        parse_spec({"name": "x", "run_at": naive})
    with pytest.raises(InvalidJobSpec):
        parse_spec({"name": "x", "delay": 5, "run_at": naive.replace(tzinfo=timezone.utc)})
    berlin = timezone(timedelta(hours=1))
    spec = parse_spec({"name": "x", "run_at": datetime(2024, 3, 1, 13, 0, tzinfo=berlin)})
    assert spec.run_at == datetime(2024, 3, 1, 12, 0, tzinfo=timezone.utc)


class Resize(PayloadSchema):
    width: int
    height: int
    format: str = "png"


def test_payload_schema_normalises_and_rejects():
    assert validate_payload(Resize, {"width": "640", "height": 480}) == {"width": 640, "height": 480, "format": "png"}
    with pytest.raises(InvalidJobSpec) as info:
        validate_payload(Resize, {"width": 640, "depth": 3})
    assert {"payload.height", "payload.depth"} <= set(info.value.errors)
