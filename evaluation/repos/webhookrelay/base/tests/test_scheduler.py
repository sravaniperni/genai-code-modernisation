import threading
from datetime import datetime, timedelta

import pytest
from conftest import T0

from webhookrelay.clock import FixedClock, isoformat_z
from webhookrelay.scheduler import RetryPolicy, RetryScheduler, parse_retry_after


def test_should_retry_respects_attempts_and_status():
    policy = RetryPolicy(max_attempts=3)
    assert policy.should_retry(1, 503)
    assert policy.should_retry(2, None)
    assert policy.should_retry(1, 429)
    assert not policy.should_retry(1, 404)
    assert not policy.should_retry(3, 503)


def test_backoff_grows_and_is_capped():
    policy = RetryPolicy(base_delay=1, factor=3, max_delay=100)
    delays = [policy.delay_for(n) for n in range(1, 10)]
    assert delays == sorted(delays)
    assert delays[-1] == 100
    assert all(d > 0 for d in delays)
    with pytest.raises(ValueError):
        policy.delay_for(0)


def test_parse_retry_after():
    now = T0
    assert isoformat_z(parse_retry_after("120", now)) == "2026-01-01T12:02:00Z"
    assert isoformat_z(parse_retry_after("Thu, 01 Jan 2026 12:30:00 GMT", now)) == "2026-01-01T12:30:00Z"
    assert parse_retry_after("soon", now) is None
    assert parse_retry_after("  ", now) is None


def test_run_pending_hands_over_due_items_in_order():
    clock = FixedClock(T0)
    seen = []
    scheduler = RetryScheduler(seen.append, clock=clock)
    scheduler.schedule("c", T0 + timedelta(seconds=30))
    scheduler.schedule("a", T0 + timedelta(seconds=10))
    scheduler.schedule("b", T0 + timedelta(seconds=20))
    assert scheduler.run_pending() == 0
    clock.advance(15)
    assert scheduler.run_pending() == 1
    clock.advance(20)
    assert scheduler.run_pending() == 2
    assert seen == ["a", "b", "c"]
    assert scheduler.describe()["pending"] == 0


def test_naive_due_times_are_utc():
    scheduler = RetryScheduler(lambda item: None, clock=FixedClock(T0))
    scheduler.schedule("x", datetime(2026, 1, 1, 12, 5))
    assert scheduler.describe()["next_due"] == "2026-01-01T12:05:00Z"
    assert isoformat_z(scheduler.pending()[0].due_at) == "2026-01-01T12:05:00Z"


def test_worker_thread_processes_due_items():
    fired = threading.Event()
    scheduler = RetryScheduler(lambda item: fired.set(), clock=FixedClock(T0), poll_interval=0.01)
    scheduler.schedule("x", T0 - timedelta(seconds=1))
    scheduler.start()
    try:
        assert scheduler.running
        assert fired.wait(5)
        assert scheduler.describe()["worker"] == "webhookrelay-retry"
    finally:
        scheduler.stop()
    assert not scheduler.running
