import importlib.metadata
from datetime import datetime, timedelta, timezone

import pytest

from jobqueue.clock import FrozenClock
from jobqueue.cron import CronSchedule
from jobqueue.errors import InvalidSchedule
from jobqueue.queue import JobQueue
from jobqueue.scheduler import RecurringScheduler


def utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


def test_arrow_version_is_pinned():
    assert importlib.metadata.version("arrow") == "1.3.0"


def test_next_timestamp_is_whole_seconds():
    schedule = CronSchedule("*/10 * * * *")
    value = schedule.next_timestamp(utc(2024, 5, 6, 8, 3, 59, 900000))
    assert type(value) is int
    assert value == int(utc(2024, 5, 6, 8, 10).timestamp())


def test_time_zones():
    after = utc(2024, 1, 15, 12, 0, 30)
    assert CronSchedule("0 9 * * *", tz="America/New_York").next_after(after) == utc(2024, 1, 15, 14, 0)
    assert CronSchedule("30 17 * * *", tz="Asia/Kolkata").next_after(after) == utc(2024, 1, 16, 12, 0)
    tokyo = CronSchedule("0 0 1 * *", tz="Asia/Tokyo")
    assert tokyo.next_after(after) == utc(2024, 1, 31, 15, 0)
    assert tokyo.next_timestamp(after) == int(utc(2024, 1, 31, 15, 0).timestamp())
    result = CronSchedule("15 3 * * *", tz="Europe/Paris").next_after(after)
    assert result == utc(2024, 1, 16, 2, 15) and result.utcoffset() == timedelta(0)


def test_calendar_rollovers():
    assert CronSchedule("0 0 1 1 *").next_after(utc(2024, 12, 31, 23, 59, 59)) == utc(2025, 1, 1)
    assert CronSchedule("0 12 31 * *").next_after(utc(2024, 4, 1, 0, 0, 1)) == utc(2024, 5, 31, 12, 0)


def test_unknown_time_zone():
    with pytest.raises(InvalidSchedule):
        CronSchedule("* * * * *", tz="Atlantis/Capital")


def test_scheduler_ticks():
    clock = FrozenClock(utc(2024, 5, 6, 7, 58, 20))
    queue = JobQueue(clock=clock)
    scheduler = RecurringScheduler(queue)
    entry = scheduler.add("digest", "0 * * * *", "send-digest", {"list": "ops"}, priority=6)
    assert entry.next_fire == int(utc(2024, 5, 6, 8, 0).timestamp())
    assert scheduler.tick(utc(2024, 5, 6, 7, 59, 59)) == []
    [first] = scheduler.tick(utc(2024, 5, 6, 8, 0, 1))
    assert first.payload == {"list": "ops", "scheduled_for": "2024-05-06T08:00:00+00:00"} and first.priority == 6
    assert entry.next_fire == int(utc(2024, 5, 6, 9, 0).timestamp())
    late = scheduler.tick(utc(2024, 5, 6, 11, 42, 7))
    assert [job.payload["scheduled_for"] for job in late] == ["2024-05-06T09:00:00+00:00"]
    assert entry.next_fire == int(utc(2024, 5, 6, 12, 0).timestamp()) and entry.fired == 2
    assert scheduler.tick() == []
    clock.advance(hours=5)
    assert len(scheduler.tick()) == 1
    assert len(queue.store.list()) == 3
