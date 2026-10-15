import pytest

from jobqueue.retry import RetryPolicy


def test_delays_grow_and_are_capped():
    policy = RetryPolicy(base_delay=1.0, factor=10.0, max_delay=50.0)
    delays = [policy.delay_for(n) for n in range(1, 8)]
    assert delays == sorted(delays)
    assert max(delays) == 50.0 and delays[-1] == 50.0
    assert policy.delay_for(5000) == 50.0


def test_jitter_is_bounded_and_reproducible():
    plain = RetryPolicy(base_delay=4.0, factor=2.0)
    jittered = RetryPolicy(base_delay=4.0, factor=2.0, jitter=0.2, seed=7)
    again = RetryPolicy(base_delay=4.0, factor=2.0, jitter=0.2, seed=7)
    for n in range(1, 6):
        assert jittered.delay_for(n) == again.delay_for(n)
        assert 0.8 * plain.delay_for(n) <= jittered.delay_for(n) <= 1.2 * plain.delay_for(n)


def test_invalid_policies_and_retry_numbers_rejected():
    for kwargs in ({"factor": 0.5}, {"jitter": 1.0}, {"base_delay": -1}):
        with pytest.raises(ValueError):
            RetryPolicy(**kwargs)
    with pytest.raises(ValueError):
        RetryPolicy().delay_for(0)
