import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from webhookrelay.clock import FixedClock, SystemClock, ensure_utc, from_epoch, isoformat_z, to_epoch
from webhookrelay.config import load_config
from webhookrelay.delivery import Dispatcher
from webhookrelay.payloads import Event
from webhookrelay.scheduler import RetryScheduler, parse_retry_after
from webhookrelay.signatures import SignatureError, sign_payload, verify_hmac
from webhookrelay.transports import HttpxTransport

UTC = timezone.utc
ISO_Z = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
SECRET = "src-secret-8e7d6c5b4a3f2e1d0c9b8a7f6e5d4c3b"


def is_aware_utc(value):
    return value.tzinfo is not None and value.utcoffset() == timedelta(0)


def test_system_clock_is_aware_utc():
    now = SystemClock().now()
    assert is_aware_utc(now)
    assert abs(now.timestamp() - time.time()) < 60


def test_epoch_conversions():
    value = from_epoch(1767268800)
    assert is_aware_utc(value)
    assert value == datetime(2026, 1, 1, 12, tzinfo=UTC)
    assert to_epoch(value) == 1767268800
    assert to_epoch(datetime(2026, 1, 1, 12)) == 1767268800
    assert to_epoch(datetime(2026, 1, 1, 14, tzinfo=timezone(timedelta(hours=2)))) == 1767268800


def test_normalisation_and_formatting():
    plus_two = timezone(timedelta(hours=2))
    assert ensure_utc(datetime(2026, 1, 1, 12)) == datetime(2026, 1, 1, 12, tzinfo=UTC)
    assert is_aware_utc(ensure_utc(datetime(2026, 1, 1, 12)))
    converted = ensure_utc(datetime(2026, 1, 1, 14, 30, tzinfo=plus_two))
    assert is_aware_utc(converted) and converted.hour == 12 and converted.minute == 30
    assert isoformat_z(datetime(2026, 1, 1, 12, 0, 0, 999999)) == "2026-01-01T12:00:00Z"
    assert isoformat_z(datetime(2026, 1, 1, 14, 0, tzinfo=plus_two)) == "2026-01-01T12:00:00Z"
    assert isoformat_z(from_epoch(1767268800.5)) == "2026-01-01T12:00:00Z"
    assert isoformat_z(None) is None


def test_fixed_clock_is_aware_utc():
    clock = FixedClock(datetime(2026, 1, 1, 12))
    assert is_aware_utc(clock.now()) and clock.now() == datetime(2026, 1, 1, 12, tzinfo=UTC)
    assert clock.advance(90) == datetime(2026, 1, 1, 12, 1, 30, tzinfo=UTC)
    shifted = FixedClock(datetime(2026, 1, 1, 9, tzinfo=timezone(timedelta(hours=-3))))
    assert shifted.now() == datetime(2026, 1, 1, 12, tzinfo=UTC) and is_aware_utc(shifted.now())


def test_signature_tolerance_with_the_system_clock():
    body = b'{"id": 1}'
    now = int(time.time())
    verify_hmac(SECRET, body, sign_payload(SECRET, body, now), str(now))
    with pytest.raises(SignatureError, match="tolerance"):
        verify_hmac(SECRET, body, sign_payload(SECRET, body, now - 3600), str(now - 3600), tolerance=300)
    clock = FixedClock(datetime(2026, 1, 1, 12))
    verify_hmac(SECRET, body, sign_payload(SECRET, body, 1767268790), "1767268790", clock=clock)


def test_scheduler_with_the_system_clock():
    seen = []
    scheduler = RetryScheduler(seen.append)
    scheduler.schedule("naive", datetime(2000, 1, 1))
    scheduler.schedule("aware", datetime(2000, 1, 1, 1, tzinfo=timezone(timedelta(hours=5))))
    scheduler.schedule("future", datetime(2999, 1, 1, tzinfo=UTC))
    assert scheduler.run_pending() == 2
    assert seen == ["aware", "naive"]
    assert all(is_aware_utc(item.due_at) for item in scheduler.pending())
    assert scheduler.describe()["next_due"] == "2999-01-01T00:00:00Z"


def test_retry_after_dates():
    now = datetime(2026, 1, 1, 12, tzinfo=UTC)
    in_two_minutes = parse_retry_after("120", now)
    assert in_two_minutes == datetime(2026, 1, 1, 12, 2, tzinfo=UTC) and is_aware_utc(in_two_minutes)
    assert parse_retry_after("120", datetime(2026, 1, 1, 12)) == in_two_minutes
    http_date = parse_retry_after("Thu, 01 Jan 2026 12:30:00 GMT", now)
    assert http_date == datetime(2026, 1, 1, 12, 30, tzinfo=UTC) and is_aware_utc(http_date)


def test_dispatcher_with_the_system_clock():
    def handler(request):
        return httpx.Response(503)

    config = load_config({"targets": {"t": {"url": "https://t.example/in", "secret": SECRET}},
                          "rules": [{"targets": ["t"]}], "retry": {"base_delay": 30}})
    dispatcher = Dispatcher(config, transport=HttpxTransport(transport=httpx.MockTransport(handler)))
    before = time.time()
    [record] = dispatcher.dispatch(Event("shop", "order.created", "o-1", {}, SystemClock().now(), {}))
    assert is_aware_utc(record.attempted_at) and is_aware_utc(record.next_retry_at)
    assert abs(record.attempted_at.timestamp() - before) < 60
    assert record.next_retry_at - record.attempted_at == timedelta(seconds=30)
    data = record.to_dict()
    assert ISO_Z.match(data["attempted_at"]) and ISO_Z.match(data["next_retry_at"])
    assert dispatcher.scheduler.run_pending() == 0
    assert dispatcher.scheduler.describe()["pending"] == 1


def test_deprecated_calls_are_gone():
    src = Path(os.environ["REPO_ROOT"]) / "src"
    offenders = [
        f"{path.relative_to(src)}:{lineno}"
        for path in src.rglob("*.py")
        for lineno, line in enumerate(path.read_text().splitlines(), 1)
        if re.search(r"\butcnow\s*\(|\butcfromtimestamp\s*\(", line)
    ]
    assert offenders == []
