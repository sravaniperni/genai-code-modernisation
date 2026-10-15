from datetime import datetime, timezone

import pytest

from jobqueue.clock import FrozenClock
from jobqueue.queue import JobQueue
from jobqueue.registry import HandlerRegistry
from jobqueue.store import MemoryJobStore

# A Friday morning; seconds are deliberately not zero.
START = datetime(2024, 3, 1, 9, 59, 30, tzinfo=timezone.utc)


@pytest.fixture
def clock():
    return FrozenClock(START)


@pytest.fixture
def registry():
    registry = HandlerRegistry()
    registry.register("add", lambda payload: payload["a"] + payload["b"])
    return registry


@pytest.fixture
def queue(clock, registry):
    return JobQueue(MemoryJobStore(), registry=registry, clock=clock)
