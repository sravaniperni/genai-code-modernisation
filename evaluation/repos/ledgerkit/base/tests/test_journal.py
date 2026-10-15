import re
from datetime import date
from decimal import Decimal

import pytest

from conftest import entry
from ledgerkit.errors import AccountNotFoundError, CurrencyMismatchError, PeriodClosedError, UnbalancedEntryError
from ledgerkit.journal import JournalEntry, Ledger, Posting
from ledgerkit.money import Money


def test_balances_use_natural_sign(ledger):
    assert ledger.balance("1000") == Money("9200", "USD")
    assert ledger.balance("4000") == Money("2900.00", "USD")
    assert ledger.balance("3000").amount == Decimal("10000")
    assert ledger.totals("1000") == (Decimal("10400"), Decimal("1200"))


def test_balance_restricted_to_dates(ledger):
    assert ledger.balance("4000", end=date(2024, 1, 12)).amount == Decimal("2500.00")
    assert ledger.balance("4000", start=date(2024, 1, 12)).amount == Decimal("400")
    assert [e.description for e in ledger.entries_between(date(2024, 1, 3), date(2024, 1, 16))] == ["Invoice 1", "Cash sale"]


def test_unbalanced_entries_are_rejected(ledger):
    with pytest.raises(UnbalancedEntryError):
        ledger.post(entry(date(2024, 2, 1), "Typo", Posting.debit("6100", "100.00"), Posting.credit("1000", "90.00")))
    with pytest.raises(UnbalancedEntryError):
        ledger.post(entry(date(2024, 2, 1), "Single line", Posting.debit("6100", "100.00")))
    with pytest.raises(UnbalancedEntryError):
        ledger.post(entry(date(2024, 2, 1), "Zero", Posting.debit("6100", "0"), Posting.credit("1000", "0")))


def test_sub_cent_conversion_noise_is_tolerated(ledger):
    posted = ledger.post(entry(date(2024, 2, 1), "Converted", Posting.debit("6100", "33.333"),
                               Posting.credit("1000", "33.33")))
    assert posted in ledger.entries


def test_posting_checks_accounts_and_currencies(ledger):
    with pytest.raises(AccountNotFoundError):
        ledger.post(entry(date(2024, 2, 1), "x", Posting.debit("9999", "1"), Posting.credit("1000", "1")))
    with pytest.raises(CurrencyMismatchError):
        ledger.post(entry(date(2024, 2, 1), "x", Posting.debit("1200", "5", "USD"), Posting.credit("1000", "5")))


def test_locked_period_rejects_postings(ledger):
    ledger.locked_through = date(2024, 1, 31)
    with pytest.raises(PeriodClosedError):
        ledger.post(entry(date(2024, 1, 25), "Late", Posting.debit("6100", "1"), Posting.credit("1000", "1")))
    ledger.post(entry(date(2024, 2, 1), "Fine", Posting.debit("6100", "1"), Posting.credit("1000", "1")))


def test_entry_serialisation_round_trip(ledger):
    original = ledger.entries[1]
    data = original.to_dict()
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", data["created_at"])
    restored = JournalEntry.from_dict(data)
    assert restored.to_dict() == data
    assert restored.postings == original.postings


def test_ledger_round_trip(ledger):
    ledger.locked_through = date(2024, 1, 5)
    copy = Ledger.from_dict(ledger.to_dict())
    assert copy.to_dict() == ledger.to_dict()
    assert copy.balance("1000") == ledger.balance("1000")


def test_allocate_posts_balanced_entry(ledger):
    allocation = ledger.allocate(day=date(2024, 2, 5), description="Split marketing", source="1000",
                                 targets={"6100": 1, "6200": 3}, amount=Money("200.00", "USD"))
    assert [p.amount.amount for p in allocation.postings] == [Decimal("50.00"), Decimal("150.00"), Decimal("-200.00")]
    assert ledger.balance("6200") == Money("150.00", "USD")
