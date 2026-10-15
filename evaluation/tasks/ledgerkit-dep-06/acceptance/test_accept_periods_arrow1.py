import importlib.metadata
from datetime import date, datetime, timedelta, timezone

import pytest

from ledgerkit.journal import JournalEntry, Posting
from ledgerkit.periods import FiscalCalendar, Period


def _entry(day: date, created_at: datetime) -> JournalEntry:
    return JournalEntry(day, "x", (Posting.debit("6100", "1"), Posting.credit("1000", "1")), created_at=created_at)


def test_arrow_is_pinned_to_1_3_0():
    assert importlib.metadata.version("arrow") == "1.3.0"


def test_periods_and_lookup():
    calendar = FiscalCalendar(first_month=10, tz="Europe/Zurich")
    periods = calendar.periods(2024)
    assert [p.name for p in periods] == [f"FY2024-P{i:02d}" for i in range(1, 13)]
    assert periods[0] == Period("FY2024-P01", date(2024, 10, 1), date(2024, 10, 31))
    assert periods[4] == Period("FY2024-P05", date(2025, 2, 1), date(2025, 2, 28))
    assert periods[-1] == Period("FY2024-P12", date(2025, 9, 1), date(2025, 9, 30))
    assert calendar.period_for(date(2024, 9, 30)).name == "FY2023-P12"
    assert calendar.period_for(date(2025, 2, 28)).name == "FY2024-P05"
    assert FiscalCalendar().period_for(date(2024, 2, 29)) == Period("FY2024-P02", date(2024, 2, 1), date(2024, 2, 29))


@pytest.mark.parametrize(("tz", "first_month", "day", "expected"), [
    ("UTC", 1, date(2025, 2, 14), (1738368000, 1740787199)),
    ("America/New_York", 1, date(2024, 3, 15), (1709269200, 1711943999)),
    ("Europe/Zurich", 10, date(2024, 10, 2), (1727733600, 1730415599)),
])
def test_boundaries_are_whole_posix_seconds(tz, first_month, day, expected):
    calendar = FiscalCalendar(first_month=first_month, tz=tz)
    bounds = calendar.boundaries(calendar.period_for(day))
    assert bounds == expected
    assert all(type(value) is int for value in bounds)


def test_late_entries_with_naive_and_aware_timestamps():
    utc = FiscalCalendar()
    january = utc.period_for(date(2024, 1, 10))
    assert not utc.is_late(_entry(date(2024, 1, 31), datetime(2024, 2, 5, 23, 59, 59)), january)
    assert utc.is_late(_entry(date(2024, 1, 31), datetime(2024, 2, 6, 0, 0, 1)), january)
    berlin_evening = datetime(2024, 2, 6, 0, 30, tzinfo=timezone(timedelta(hours=1)))  # 23:30 UTC on the 5th
    assert not utc.is_late(_entry(date(2024, 1, 15), berlin_evening), january)
    assert utc.is_late(_entry(date(2024, 1, 15), datetime(2024, 2, 1, 0, 30)), january, grace_days=0)
    assert not utc.is_late(_entry(date(2024, 1, 15), datetime(2024, 1, 31, 23, 59)), january, grace_days=0)
    assert not utc.is_late(_entry(date(2024, 2, 1), datetime(2030, 1, 1)), january)

    zurich = FiscalCalendar(tz="Europe/Zurich")
    january_zurich = zurich.period_for(date(2024, 1, 10))
    assert zurich.is_late(_entry(date(2024, 1, 20), datetime(2024, 2, 5, 23, 30)), january_zurich)
    assert not zurich.is_late(_entry(date(2024, 1, 20), datetime(2024, 2, 5, 22, 30)), january_zurich)
    assert zurich.is_late(_entry(date(2024, 1, 20), datetime(2024, 2, 2, 0, 0, tzinfo=timezone.utc)),
                          january_zurich, grace_days=1)
