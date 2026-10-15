from datetime import datetime, timedelta, timezone

import pytest

from jobqueue.clock import FrozenClock
from jobqueue.executor import Executor
from jobqueue.job import JobState
from jobqueue.queue import JobQueue
from jobqueue.registry import HandlerRegistry
from jobqueue.retry import RetryPolicy

T0 = datetime(2024, 5, 6, 10, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "policy, expected",
    [
        (RetryPolicy(base_delay=5, factor=2), [5, 10, 20, 40]),
        (RetryPolicy(base_delay=2, factor=3), [2, 6, 18, 54]),
        (RetryPolicy(base_delay=1, factor=10, max_delay=50), [1, 10, 50, 50]),
        (RetryPolicy(base_delay=7, factor=1), [7, 7, 7, 7]),
        (RetryPolicy(base_delay=0, factor=2), [0, 0, 0, 0]),
        (RetryPolicy(), [5, 10, 20, 40]),
    ],
)
def test_documented_delays(policy, expected):
    assert [policy.delay_for(n) for n in range(1, 5)] == pytest.approx(expected)


def test_cap_is_reached_at_the_right_retry():
    policy = RetryPolicy(base_delay=30, factor=2, max_delay=200)
    assert [policy.delay_for(n) for n in range(1, 6)] == pytest.approx([30, 60, 120, 200, 200])


def test_jitter_spreads_around_documented_values():
    policy = RetryPolicy(base_delay=10, factor=2, jitter=0.25, seed=99)
    for n, nominal in zip(range(1, 6), [10, 20, 40, 80, 160]):
        assert 0.75 * nominal <= policy.delay_for(n) <= 1.25 * nominal


def test_executor_reschedules_with_documented_backoff():
    clock = FrozenClock(T0)
    registry = HandlerRegistry()
    registry.register("always-fails", lambda payload: 1 / 0)
    queue = JobQueue(registry=registry, clock=clock)
    executor = Executor(queue.store, registry, clock=clock, retry_policy=RetryPolicy(base_delay=4, factor=3))
    job = queue.enqueue("always-fails", max_attempts=4)
    expected_waits = [4, 12, 36]
    for wait in expected_waits:
        failed_at = clock.now()
        executor.execute(queue.store.claim_next(failed_at, "w"))
        pending = queue.get(job.id)
        assert pending.state == JobState.PENDING
        assert pending.run_at == failed_at + timedelta(seconds=wait)
        clock.advance(seconds=wait)
    executor.execute(queue.store.claim_next(clock.now(), "w"))
    assert queue.get(job.id).state == JobState.FAILED
