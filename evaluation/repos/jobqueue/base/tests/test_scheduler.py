from datetime import timedelta

import pytest

from jobqueue.scheduler import RecurringScheduler

from conftest import START


def test_tick_enqueues_each_fire_time_once(queue):
    scheduler = RecurringScheduler(queue)
    scheduler.add("report", "*/15 * * * *", "add", {"a": 1, "b": 2}, priority=7, queue="reports")
    first = scheduler.tick(START + timedelta(seconds=60))  # 10:00:30
    assert [job.payload["scheduled_for"] for job in first] == ["2024-03-01T10:00:00+00:00"]
    assert (first[0].priority, first[0].queue, first[0].payload["a"]) == (7, "reports", 1)
    assert scheduler.tick(START + timedelta(minutes=6)) == []  # 10:05:30
    second = scheduler.tick(START + timedelta(minutes=16))  # 10:15:30
    assert [job.payload["scheduled_for"] for job in second] == ["2024-03-01T10:15:00+00:00"]


def test_missed_fire_times_are_coalesced(queue):
    scheduler = RecurringScheduler(queue)
    entry = scheduler.add("sync", "*/15 * * * *", "add", {"a": 0, "b": 0})
    created = scheduler.tick(START + timedelta(hours=1, minutes=21))  # 11:20:30
    assert len(created) == 1 and entry.fired == 1
    assert scheduler.tick(START + timedelta(hours=1, minutes=25)) == []
    assert len(scheduler.tick(START + timedelta(hours=1, minutes=31))) == 1


def test_keys_are_unique(queue):
    scheduler = RecurringScheduler(queue)
    scheduler.add("nightly", "@daily", "add")
    with pytest.raises(ValueError):
        scheduler.add("nightly", "@hourly", "add")
