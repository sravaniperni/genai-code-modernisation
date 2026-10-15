from datetime import datetime, timedelta, timezone

from jobqueue.clock import FrozenClock
from jobqueue.cron import CronSchedule
from jobqueue.queue import JobQueue
from jobqueue.scheduler import RecurringScheduler

T0 = datetime(2024, 5, 6, 10, 0, 30, tzinfo=timezone.utc)


def utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


def test_next_after_is_strictly_later_on_boundaries():
    every_quarter = CronSchedule("*/15 * * * *")
    assert every_quarter.next_after(utc(2024, 5, 6, 10, 15)) == utc(2024, 5, 6, 10, 30)
    assert every_quarter.next_after(utc(2024, 5, 6, 10, 14, 59, 999999)) == utc(2024, 5, 6, 10, 15)
    assert every_quarter.next_after(utc(2024, 5, 6, 10, 15, 0, 1)) == utc(2024, 5, 6, 10, 30)
    assert CronSchedule("0 * * * *").next_after(utc(2024, 5, 6, 23, 0)) == utc(2024, 5, 7, 0, 0)
    assert CronSchedule("* * * * *").next_after(utc(2024, 5, 6, 10, 0)) == utc(2024, 5, 6, 10, 1)
    assert CronSchedule("@daily").next_timestamp(utc(2024, 5, 7)) == int(utc(2024, 5, 8).timestamp())
    berlin = CronSchedule("0 9 * * *", tz="Europe/Berlin")
    assert berlin.next_after(utc(2024, 5, 6, 7, 0)) == utc(2024, 5, 7, 7, 0)


def test_successive_fire_times_never_repeat():
    schedule = CronSchedule("*/20 * * * *")
    cursor, seen = utc(2024, 5, 6, 10, 0), []
    for _ in range(6):
        cursor = schedule.next_after(cursor)
        seen.append(cursor.strftime("%H:%M"))
    assert seen == ["10:20", "10:40", "11:00", "11:20", "11:40", "12:00"]


def test_minute_aligned_ticks_enqueue_each_fire_time_once():
    queue = JobQueue(clock=FrozenClock(T0))
    scheduler = RecurringScheduler(queue)
    scheduler.add("report", "*/15 * * * *", "send-report")
    created = []
    for minute in range(1, 61):
        created += scheduler.tick(T0.replace(second=0) + timedelta(minutes=minute))
    assert [job.payload["scheduled_for"][11:16] for job in created] == ["10:15", "10:30", "10:45", "11:00"]


def test_ticking_twice_at_the_same_instant():
    queue = JobQueue(clock=FrozenClock(T0))
    scheduler = RecurringScheduler(queue)
    scheduler.add("cleanup", "0 * * * *", "cleanup")
    fire = utc(2024, 5, 6, 11, 0)
    assert len(scheduler.tick(fire)) == 1
    assert scheduler.tick(fire) == []
    assert scheduler.tick(fire + timedelta(seconds=59)) == []
    assert scheduler.tick(fire + timedelta(minutes=1)) == []
    assert len(scheduler.tick(fire + timedelta(hours=1))) == 1


def test_hourly_schedule_over_a_day_of_aligned_ticks():
    queue = JobQueue(clock=FrozenClock(T0))
    scheduler = RecurringScheduler(queue)
    scheduler.add("hourly", "@hourly", "rollup")
    start = T0.replace(minute=0, second=0)
    for step in range(1, 24 * 12 + 1):  # every five minutes for a day
        scheduler.tick(start + timedelta(minutes=5 * step))
    stamps = [job.payload["scheduled_for"] for job in queue.store.list()]
    assert len(stamps) == 24 and len(set(stamps)) == 24
