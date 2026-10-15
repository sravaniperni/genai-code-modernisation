from datetime import date, datetime

import pytest

from conftest import entry
from ledgerkit.errors import PeriodClosedError
from ledgerkit.journal import Posting
from ledgerkit.money import Money
from ledgerkit.periods import FiscalCalendar, Period, close_period


def test_calendar_periods_follow_fiscal_year():
    periods = FiscalCalendar(first_month=4).periods(2024)
    assert len(periods) == 12
    assert periods[0] == Period("FY2024-P01", date(2024, 4, 1), date(2024, 4, 30))
    assert periods[10] == Period("FY2024-P11", date(2025, 2, 1), date(2025, 2, 28))
    assert periods[-1].end == date(2025, 3, 31)


def test_period_for_date():
    calendar = FiscalCalendar(first_month=7)
    assert calendar.period_for(date(2024, 6, 30)).name == "FY2023-P12"
    assert calendar.period_for(date(2024, 7, 1)).name == "FY2024-P01"
    with pytest.raises(ValueError):
        FiscalCalendar(first_month=13)


def test_boundaries_are_posix_seconds_in_calendar_zone():
    utc = FiscalCalendar().period_for(date(2024, 2, 10))
    assert FiscalCalendar().boundaries(utc) == (1706745600, 1709251199)
    zurich = FiscalCalendar(tz="Europe/Zurich")
    assert zurich.boundaries(zurich.period_for(date(2024, 2, 10))) == (1706742000, 1709247599)


def test_late_entries_are_detected():
    calendar = FiscalCalendar()
    january = calendar.period_for(date(2024, 1, 15))
    on_time = entry(date(2024, 1, 20), "x", Posting.debit("6100", "1"), Posting.credit("1000", "1"))
    on_time.created_at = datetime(2024, 2, 5, 23, 0)
    late = entry(date(2024, 1, 20), "x", Posting.debit("6100", "1"), Posting.credit("1000", "1"))
    late.created_at = datetime(2024, 2, 6, 0, 30)
    assert not calendar.is_late(on_time, january)
    assert calendar.is_late(late, january)
    assert not calendar.is_late(late, calendar.period_for(date(2024, 2, 1)))


def test_close_period_moves_income_to_retained_earnings_and_locks(chart):
    from ledgerkit.journal import Ledger
    ledger = Ledger(chart)
    ledger.post(entry(date(2024, 1, 10), "Sale", Posting.debit("1000", "900"), Posting.credit("4000", "900")))
    january = FiscalCalendar().period_for(date(2024, 1, 10))
    closing = close_period(ledger, january, "3100")
    assert closing is not None and closing.date == date(2024, 1, 31)
    assert ledger.balance("4000").is_zero()
    assert ledger.balance("3100") == Money("900", "USD")
    assert ledger.locked_through == date(2024, 1, 31)
    with pytest.raises(PeriodClosedError):
        close_period(ledger, january, "3100")
