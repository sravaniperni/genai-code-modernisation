from datetime import datetime, timedelta, timezone

import httpx
import pytest

from webhookrelay.clock import FixedClock, isoformat_z
from webhookrelay.config import load_config
from webhookrelay.delivery import Dispatcher
from webhookrelay.payloads import Event
from webhookrelay.scheduler import RetryScheduler, parse_retry_after
from webhookrelay.transports import HttpxTransport

UTC = timezone.utc
IST = timezone(timedelta(hours=5, minutes=30))
T7 = datetime(2026, 1, 1, 7, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    "header, expected",
    [
        ("Thu, 01 Jan 2026 09:30:00 +0200", "2026-01-01T07:30:00Z"),
        ("Thu, 01 Jan 2026 02:30:00 -0500", "2026-01-01T07:30:00Z"),
        ("Thu, 01 Jan 2026 13:00:00 +0530", "2026-01-01T07:30:00Z"),
        ("Thu, 01 Jan 2026 07:30:00 GMT", "2026-01-01T07:30:00Z"),
        ("Thu, 01 Jan 2026 07:30:00 +0000", "2026-01-01T07:30:00Z"),
        ("Thu, 01 Jan 2026 07:30:00 -0000", "2026-01-01T07:30:00Z"),
        ("1800", "2026-01-01T07:30:00Z"),
    ],
)
def test_retry_after_is_converted_to_utc(header, expected):
    when = parse_retry_after(header, T7)
    assert isoformat_z(when) == expected
    assert when == datetime(2026, 1, 1, 7, 30, tzinfo=UTC)


def test_scheduling_with_offsets():
    clock = FixedClock(T7)
    seen = []
    scheduler = RetryScheduler(seen.append, clock=clock)
    scheduler.schedule("india", datetime(2026, 1, 1, 13, 0, tzinfo=IST))  # 07:30Z
    scheduler.schedule("naive", datetime(2026, 1, 1, 7, 20))  # 07:20Z
    scheduler.schedule("new-york", datetime(2026, 1, 1, 2, 10, tzinfo=timezone(timedelta(hours=-5))))  # 07:10Z
    assert scheduler.describe()["next_due"] == "2026-01-01T07:10:00Z"
    assert [isoformat_z(item.due_at) for item in scheduler.pending()] == [
        "2026-01-01T07:10:00Z", "2026-01-01T07:20:00Z", "2026-01-01T07:30:00Z"]
    assert [item.due_at for item in scheduler.pending()][2] == datetime(2026, 1, 1, 7, 30, tzinfo=UTC)
    clock.advance(9 * 60)
    assert scheduler.run_pending() == 0
    clock.advance(60)
    assert scheduler.run_pending() == 1
    clock.advance(19 * 60)
    assert scheduler.run_pending() == 1
    assert seen == ["new-york", "naive"]
    clock.advance(60)
    assert scheduler.run_pending() == 1
    assert seen == ["new-york", "naive", "india"]


def test_reported_delivery_scenario():
    clock = FixedClock(T7)
    responses = [httpx.Response(503, headers={"Retry-After": "Thu, 01 Jan 2026 09:30:00 +0200"}),
                 httpx.Response(200)]

    def handler(request):
        return responses.pop(0)

    config = load_config({"targets": {"partner": {"url": "https://partner.example/in"}},
                          "rules": [{"targets": ["partner"]}]})
    dispatcher = Dispatcher(config, transport=HttpxTransport(transport=httpx.MockTransport(handler)), clock=clock)
    [record] = dispatcher.dispatch(Event("shop", "order.created", "o-1", {}, T7, {}))
    assert record.to_dict()["next_retry_at"] == "2026-01-01T07:30:00Z"
    assert dispatcher.scheduler.describe()["next_due"] == "2026-01-01T07:30:00Z"
    clock.advance(29 * 60)
    assert dispatcher.scheduler.run_pending() == 0
    clock.advance(60)
    assert dispatcher.scheduler.run_pending() == 1
    assert [(r.attempt, r.status) for r in dispatcher.attempts] == [(1, 503), (2, 200)]
