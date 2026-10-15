"""Fiscal calendars, accounting periods and period-end closing."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import arrow

from ledgerkit.accounts import AccountType
from ledgerkit.errors import PeriodClosedError
from ledgerkit.journal import JournalEntry, Ledger, Posting
from ledgerkit.money import Money


@dataclass(frozen=True)
class Period:
    name: str
    start: date
    end: date  # inclusive

    def contains(self, day: date) -> bool:
        return self.start <= day <= self.end


class FiscalCalendar:
    """Monthly periods of fiscal years starting on the first day of ``first_month``.

    Fiscal years are named after the calendar year they start in: with ``first_month=4``, ``FY2024``
    runs from 2024-04-01 to 2025-03-31 and its first period ``FY2024-P01`` is April 2024.
    """

    def __init__(self, first_month: int = 1, tz: str = "UTC"):
        if not 1 <= first_month <= 12:
            raise ValueError("first_month must be between 1 and 12")
        self.first_month, self.tz = first_month, tz

    def periods(self, fiscal_year: int) -> list[Period]:
        start = arrow.Arrow(fiscal_year, self.first_month, 1, tzinfo=self.tz)
        spans = arrow.Arrow.span_range("month", start, start.shift(months=11))
        return [Period(f"FY{fiscal_year}-P{i:02d}", lo.date(), hi.date()) for i, (lo, hi) in enumerate(spans, 1)]

    def period_for(self, day: date) -> Period:
        fiscal_year = day.year if day.month >= self.first_month else day.year - 1
        return next(p for p in self.periods(fiscal_year) if p.contains(day))

    def boundaries(self, period: Period) -> tuple[int, int]:
        """POSIX timestamps (whole seconds) of the first and last second of ``period`` in the calendar's zone."""
        first = arrow.Arrow.fromdate(period.start, tzinfo=self.tz)
        return first.timestamp, arrow.Arrow.fromdate(period.end, tzinfo=self.tz).ceil("day").timestamp

    def is_late(self, entry: JournalEntry, period: Period, grace_days: int = 5) -> bool:
        """True for entries dated in ``period`` but created after the end of its ``grace_days``th
        following day (naive ``created_at`` values are taken to be UTC)."""
        deadline = arrow.Arrow.fromdate(period.end, tzinfo=self.tz).shift(days=grace_days).ceil("day")
        return period.contains(entry.date) and arrow.get(entry.created_at).timestamp > deadline.timestamp


def close_period(ledger: Ledger, period: Period, retained_earnings: str) -> JournalEntry | None:
    """Zero every income and expense account for ``period`` into ``retained_earnings`` and lock the books.

    Each income/expense account gets a posting reversing its net movement in the period, and retained
    earnings is credited with the net income (debited with a net loss). Nothing dated on or before
    ``period.end`` can be posted afterwards. Returns the closing entry (``None`` if nothing to close).
    """
    if ledger.locked_through is not None and period.end <= ledger.locked_through:
        raise PeriodClosedError(f"{period.name} is already closed")
    postings: list[Posting] = []
    net: dict[str, Decimal] = {}
    for account in ledger.chart:
        if account.type in (AccountType.INCOME, AccountType.EXPENSE):
            debits, credits = ledger.totals(account.code, period.start, period.end)
            if debits != credits:
                postings.append(Posting(account.code, Money(credits - debits, account.currency), "period close"))
                net[account.currency] = net.get(account.currency, Decimal(0)) + debits - credits
    entry = None
    if postings:
        postings += [Posting(retained_earnings, Money(v, cur), "net income") for cur, v in net.items() if v != 0]
        entry = ledger.post(JournalEntry(period.end, f"Close {period.name}", tuple(postings),
                                         reference=f"CLOSE-{period.name}"))
    ledger.locked_through = period.end
    return entry
