"""Retry policies with capped exponential backoff."""

from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass(frozen=True)
class RetryPolicy:
    """How long to wait before retrying a failed job.

    ``delay_for(n)`` is the wait before retry ``n`` (``n == 1`` is the first retry, made after the first
    failed attempt). The delay starts at ``base_delay``, is multiplied by ``factor`` for every further retry
    and never exceeds ``max_delay``. ``jitter`` spreads delays by up to that fraction in either direction;
    pass ``seed`` to make the spread reproducible.
    """

    base_delay: float = 5.0
    factor: float = 2.0
    max_delay: float = 3600.0
    jitter: float = 0.0
    seed: int | None = None

    def __post_init__(self) -> None:
        if self.base_delay < 0 or self.max_delay < 0 or self.factor < 1 or not 0 <= self.jitter < 1:
            raise ValueError("invalid retry policy: delays must be >= 0, factor >= 1 and jitter in [0, 1)")

    def delay_for(self, retry_number: int) -> float:
        if retry_number < 1:
            raise ValueError("retry numbers start at 1")
        try:
            delay = min(self.base_delay * self.factor ** (retry_number - 1), self.max_delay)
        except OverflowError:
            delay = self.max_delay
        if self.jitter:
            rng = random.Random(self.seed * 1000 + retry_number) if self.seed is not None else random.Random()
            delay *= 1 + rng.uniform(-self.jitter, self.jitter)
        return delay
