from datetime import datetime, timezone

import pytest

from jobqueue.cron import CronSchedule
from jobqueue.errors import InvalidSchedule


def utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


def test_invalid_expressions_rejected():
    cases = [("* * * *", "UTC"), ("61 * * * *", "UTC"), ("*/0 * * * *", "UTC"), ("5-1 * * * *", "UTC"),
             ("0 0 * foo *", "UTC"), ("0 0 * * *", "Mars/Olympus_Mons")]
    for expression, tz in cases:
        with pytest.raises(InvalidSchedule):
            CronSchedule(expression, tz)


def test_next_after():
    cases = [
        ("*/15 * * * *", utc(2024, 3, 1, 10, 7, 12), utc(2024, 3, 1, 10, 15)),
        ("5,35 9-17 * * *", utc(2024, 3, 1, 17, 40, 10), utc(2024, 3, 2, 9, 5)),
        ("0 6 1 jan,jul *", utc(2024, 3, 1, 9, 59, 30), utc(2024, 7, 1, 6, 0)),
        ("@hourly", utc(2024, 12, 31, 23, 30, 1), utc(2025, 1, 1, 0, 0)),
        ("0 12 29 2 *", utc(2024, 3, 1, 9, 59, 30), utc(2028, 2, 29, 12, 0)),
        ("10/20 * * * *", utc(2024, 3, 1, 10, 31, 5), utc(2024, 3, 1, 10, 50)),
    ]
    for expression, after, expected in cases:
        assert CronSchedule(expression).next_after(after) == expected, expression


def test_schedules_are_evaluated_in_their_time_zone():
    # 08:30 in Berlin is 07:30 UTC in winter
    schedule = CronSchedule("30 8 * * *", tz="Europe/Berlin")
    assert schedule.next_after(utc(2024, 3, 1, 9, 59, 30)) == utc(2024, 3, 2, 7, 30)


def test_impossible_schedule_reports_error():
    with pytest.raises(InvalidSchedule):
        CronSchedule("0 0 30 2 *").next_after(utc(2024, 3, 1, 9, 59, 30))


def test_next_timestamp_matches_next_after():
    schedule = CronSchedule("*/5 * * * *")
    after = utc(2024, 3, 1, 9, 59, 30)
    assert schedule.next_timestamp(after) == int(schedule.next_after(after).timestamp())
