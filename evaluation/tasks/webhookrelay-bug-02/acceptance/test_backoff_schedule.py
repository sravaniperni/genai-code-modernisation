from datetime import datetime, timezone

import httpx
import pytest

from webhookrelay.clock import FixedClock, isoformat_z
from webhookrelay.config import load_config
from webhookrelay.delivery import Dispatcher
from webhookrelay.payloads import Event
from webhookrelay.scheduler import RetryPolicy
from webhookrelay.transports import HttpxTransport

T0 = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "policy, expected",
    [
        (RetryPolicy(base_delay=2, factor=2, max_delay=300), [2, 4, 8, 16, 32, 64, 128, 256, 300, 300]),
        (RetryPolicy(base_delay=60, factor=3, max_delay=3600), [60, 180, 540, 1620, 3600, 3600]),
        (RetryPolicy(base_delay=5, factor=1, max_delay=10), [5, 5, 5]),
        (RetryPolicy(base_delay=0.5, factor=2, max_delay=1), [0.5, 1, 1]),
    ],
)
def test_delay_sequence(policy, expected):
    assert [policy.delay_for(n) for n in range(1, len(expected) + 1)] == expected


def test_default_policy_matches_documentation():
    policy = RetryPolicy()
    assert [policy.delay_for(n) for n in (1, 2, 3, 4)] == [2, 4, 8, 16]
    with pytest.raises(ValueError):
        policy.delay_for(0)


def make_dispatcher(responses, clock, retry):
    queue = list(responses)

    def handler(request):
        return queue.pop(0)

    config = load_config({"targets": {"crm": {"url": "https://crm.example/in"}}, "rules": [{"targets": ["crm"]}],
                          "retry": retry})
    return Dispatcher(config, transport=HttpxTransport(transport=httpx.MockTransport(handler)), clock=clock)


def test_retries_are_scheduled_as_configured():
    clock = FixedClock(T0)
    dispatcher = make_dispatcher([httpx.Response(503)] * 3 + [httpx.Response(200)], clock,
                                 {"base_delay": 2, "factor": 2, "max_delay": 300, "max_attempts": 5})
    [first] = dispatcher.dispatch(Event("shop", "order.created", "o-1", {}, T0, {}))
    assert first.to_dict()["next_retry_at"] == "2026-01-01T12:00:02Z"
    clock.advance(2)
    assert dispatcher.scheduler.run_pending() == 1
    assert isoformat_z(dispatcher.attempts[-1].next_retry_at) == "2026-01-01T12:00:06Z"
    clock.advance(4)
    assert dispatcher.scheduler.run_pending() == 1
    assert isoformat_z(dispatcher.attempts[-1].next_retry_at) == "2026-01-01T12:00:14Z"
    clock.advance(7)
    assert dispatcher.scheduler.run_pending() == 0
    clock.advance(1)
    assert dispatcher.scheduler.run_pending() == 1
    assert [(r.attempt, r.status) for r in dispatcher.attempts] == [(1, 503), (2, 503), (3, 503), (4, 200)]


def test_attempt_limit_statuses_and_retry_after_are_unchanged():
    policy = RetryPolicy(max_attempts=3)
    assert policy.should_retry(2, 503) and not policy.should_retry(3, 503)
    assert policy.should_retry(1, None) and policy.should_retry(1, 429) and not policy.should_retry(1, 422)
    clock = FixedClock(T0)
    dispatcher = make_dispatcher([httpx.Response(429, headers={"Retry-After": "45"}), httpx.Response(503)], clock,
                                 {"base_delay": 2, "factor": 2, "max_attempts": 2})
    [first] = dispatcher.dispatch(Event("shop", "order.created", "o-2", {}, T0, {}))
    assert first.to_dict()["next_retry_at"] == "2026-01-01T12:00:45Z"
    clock.advance(45)
    assert dispatcher.scheduler.run_pending() == 1
    assert dispatcher.attempts[-1].next_retry_at is None
    assert dispatcher.scheduler.pending() == []
