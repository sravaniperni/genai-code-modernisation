from datetime import datetime, timedelta, timezone

import pytest

from jobqueue.clock import FrozenClock
from jobqueue.cron import CronSchedule
from jobqueue.queue import JobQueue
from jobqueue.scheduler import RecurringScheduler

FRIDAY = datetime(2024, 3, 1, 10, 0, tzinfo=timezone.utc)  # Friday 1 March 2024


def utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "expression, expected",
    [
        ("0 9 * * mon", utc(2024, 3, 4, 9, 0)),
        ("0 9 * * 1", utc(2024, 3, 4, 9, 0)),
        ("0 9 * * 1-5", utc(2024, 3, 4, 9, 0)),
        ("0 9 * * mon-fri", utc(2024, 3, 4, 9, 0)),
        ("0 0 * * 0", utc(2024, 3, 3, 0, 0)),
        ("0 0 * * 7", utc(2024, 3, 3, 0, 0)),
        ("0 0 * * sun", utc(2024, 3, 3, 0, 0)),
        ("@weekly", utc(2024, 3, 3, 0, 0)),
        ("30 6 * * sat", utc(2024, 3, 2, 6, 30)),
        ("0 12 * * 5", utc(2024, 3, 1, 12, 0)),
        ("0 8 * * fri", utc(2024, 3, 8, 8, 0)),
        ("0 8 * * tue,thu", utc(2024, 3, 5, 8, 0)),
        ("0 8 * * 3", utc(2024, 3, 6, 8, 0)),
    ],
)
def test_weekday_numbering(expression, expected):
    assert CronSchedule(expression).next_after(FRIDAY) == expected


def test_weekday_sequence_over_a_fortnight():
    schedule = CronSchedule("0 18 * * 1,3,5")
    moments, cursor = [], FRIDAY
    for _ in range(6):
        cursor = schedule.next_after(cursor)
        moments.append(cursor)
    assert [m.strftime("%a %d") for m in moments] == ["Fri 01", "Mon 04", "Wed 06", "Fri 08", "Mon 11", "Wed 13"]


def test_day_of_month_or_day_of_week():
    schedule = CronSchedule("0 12 15 * sat")
    assert schedule.next_after(FRIDAY) == utc(2024, 3, 2, 12, 0)
    assert schedule.next_after(utc(2024, 3, 9, 13, 0)) == utc(2024, 3, 15, 12, 0)


def test_weekdays_use_the_schedule_time_zone():
    # 01:30 on Monday in Sydney (UTC+11) is still Sunday in UTC
    schedule = CronSchedule("30 1 * * mon", tz="Australia/Sydney")
    assert schedule.next_after(FRIDAY) == utc(2024, 3, 3, 14, 30)


def test_scheduler_fires_on_mondays():
    clock = FrozenClock(FRIDAY)
    queue = JobQueue(clock=clock)
    scheduler = RecurringScheduler(queue)
    scheduler.add("weekly-report", "0 9 * * mon", "report")
    fired = []
    for hours in range(0, 24 * 10, 1):
        moment = FRIDAY + timedelta(hours=hours, seconds=30)
        fired += [job.payload["scheduled_for"] for job in scheduler.tick(moment)]
    assert fired == ["2024-03-04T09:00:00+00:00", "2024-03-11T09:00:00+00:00"]
