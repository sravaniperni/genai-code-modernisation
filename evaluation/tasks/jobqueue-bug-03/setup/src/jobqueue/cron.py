"""Cron-style recurring schedules: ``minute hour day-of-month month day-of-week``."""

from __future__ import annotations

from datetime import datetime

import arrow

from jobqueue.clock import ensure_utc
from jobqueue.errors import InvalidSchedule

ALIASES = {"@hourly": "0 * * * *", "@daily": "0 0 * * *", "@midnight": "0 0 * * *", "@weekly": "0 0 * * 0",
           "@monthly": "0 0 1 * *", "@yearly": "0 0 1 1 *", "@annually": "0 0 1 1 *"}
MONTHS = {name: number for number, name in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split(), 1)}
WEEKDAYS = {name: number for number, name in enumerate("sun mon tue wed thu fri sat".split())}
# label, lowest value, highest value, accepted names
FIELDS = (("minute", 0, 59, {}), ("hour", 0, 23, {}), ("day of month", 1, 31, {}), ("month", 1, 12, MONTHS),
          ("day of week", 0, 7, WEEKDAYS))
SEARCH_YEARS = 5


def _value(text: str, label: str, low: int, high: int, names: dict[str, int]) -> int:
    if text.lower() in names:
        return names[text.lower()]
    if not text.isdigit() or not low <= int(text) <= high:
        raise InvalidSchedule(f"invalid {label} value {text!r} (expected {low}-{high})")
    return int(text)


def _field(text: str, label: str, low: int, high: int, names: dict[str, int]) -> frozenset[int]:
    values: set[int] = set()
    for part in text.split(","):
        step = 1
        if "/" in part:
            part, step_text = part.split("/", 1)
            if not step_text.isdigit() or int(step_text) == 0:
                raise InvalidSchedule(f"invalid step in {label} field {text!r}")
            step = int(step_text)
        if part == "*":
            start, end = low, high
        elif "-" in part:
            first, last = part.split("-", 1)
            start, end = _value(first, label, low, high, names), _value(last, label, low, high, names)
            if start > end:
                raise InvalidSchedule(f"empty range {part!r} in {label} field")
        else:
            start = _value(part, label, low, high, names)
            end = high if step > 1 else start
        values.update(range(start, end + 1, step))
    return frozenset(values)


class CronSchedule:
    """A parsed cron expression evaluated in time zone ``tz``.

    Day of week uses cron numbering (0 or 7 = Sunday, 1 = Monday ... 6 = Saturday). When both the
    day-of-month and the day-of-week fields are restricted, a day matches if either field matches.
    """

    def __init__(self, expression: str, tz: str = "UTC"):
        self.expression = expression.strip()
        parts = ALIASES.get(self.expression.lower(), self.expression).split()
        if len(parts) != 5:
            raise InvalidSchedule(f"expected 5 fields in {expression!r}, got {len(parts)}")
        parsed = [_field(text, *spec) for text, spec in zip(parts, FIELDS)]
        self.minutes, self.hours, self.days, self.months, weekdays = parsed
        self.weekdays = frozenset(day % 7 for day in weekdays)
        self._any_day, self._any_weekday = parts[2].startswith("*"), parts[4].startswith("*")
        try:
            arrow.now(tz)
        except ValueError as exc:
            raise InvalidSchedule(f"unknown time zone {tz!r}") from exc
        self.tz = tz

    def _day_matches(self, moment: arrow.Arrow) -> bool:
        by_date = moment.day in self.days
        by_weekday = moment.weekday() in self.weekdays
        if self._any_day or self._any_weekday:
            return by_weekday if self._any_day else by_date
        return by_date or by_weekday

    def next_after(self, after: datetime) -> datetime:
        """Return the first fire time strictly after ``after``, as an aware UTC datetime."""
        cursor = arrow.get(ensure_utc(after)).to(self.tz).floor("minute").shift(minutes=1)
        limit = cursor.shift(years=SEARCH_YEARS)
        while cursor < limit:
            if cursor.month not in self.months:
                cursor = cursor.floor("month").shift(months=1)
            elif not self._day_matches(cursor):
                cursor = cursor.floor("day").shift(days=1)
            elif cursor.hour not in self.hours:
                cursor = cursor.floor("hour").shift(hours=1)
            elif cursor.minute not in self.minutes:
                cursor = cursor.shift(minutes=1)
            else:
                return ensure_utc(cursor.to("UTC").datetime)
        raise InvalidSchedule(f"{self.expression!r} does not fire within {SEARCH_YEARS} years")

    def next_timestamp(self, after: datetime) -> int:
        """POSIX timestamp (whole seconds) of :meth:`next_after`."""
        return arrow.get(self.next_after(after)).timestamp
