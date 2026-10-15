import importlib.metadata
from datetime import date, datetime
from decimal import Decimal

import pytest

from ledgerkit.accounts import Account, AccountType, ChartOfAccounts
from ledgerkit.journal import JournalEntry, Posting
from ledgerkit.store import LedgerStore


def _chart():
    return ChartOfAccounts([
        Account("1000", "Cash", AccountType.ASSET),
        Account("1300", "Bank JPY", AccountType.ASSET, "JPY"),
        Account("1400", "Bank BHD", AccountType.ASSET, "BHD"),
        Account("3000", "Capital", AccountType.EQUITY),
        Account("4000", "Sales", AccountType.INCOME),
        Account("4200", "Sales JPY", AccountType.INCOME, "JPY"),
        Account("4300", "Sales BHD", AccountType.INCOME, "BHD"),
        Account("6000", "Expenses", AccountType.EXPENSE),
        Account("6100", "Rent", AccountType.EXPENSE, parent="6000"),
    ])


def _entries():
    stamp = datetime(2024, 3, 1, 9, 30, 15)
    return [
        JournalEntry(date(2024, 3, 1), "Capital", (Posting.debit("1000", "10000.00"), Posting.credit("3000", "10000.00")),
                     reference="CAP", entry_id="e-capital", created_at=stamp),
        JournalEntry(date(2024, 3, 5), "Tokyo sale", (Posting.debit("1300", "125000", "JPY", memo="inv 9"),
                                                     Posting.credit("4200", "125000", "JPY")),
                     reference="JP-9", entry_id="e-tokyo", created_at=stamp),
        JournalEntry(date(2024, 3, 8), "Manama sale", (Posting.debit("1400", "12.345", "BHD"),
                                                      Posting.credit("4300", "12.345", "BHD")),
                     entry_id="e-manama", created_at=stamp),
        JournalEntry(date(2024, 3, 20), "Rent", (Posting.debit("6100", "1250.50"), Posting.credit("1000", "1000.25"),
                                                Posting.credit("1000", "250.25", memo="fees")),
                     reference="R-3", entry_id="e-rent", created_at=stamp),
        JournalEntry(date(2024, 3, 25), "Sale", (Posting.debit("1000", "99.99"), Posting.credit("4000", "99.99")),
                     entry_id="e-sale", created_at=stamp),
    ]


def _filled(url="sqlite://"):
    store = LedgerStore(url)
    store.save_chart(_chart())
    for entry in _entries():
        store.save_entry(entry)
    return store


def _summary(entries):
    return [(e.entry_id, e.date, e.description, e.reference, e.created_at, e.postings) for e in entries]


def test_sqlalchemy_is_pinned_to_2_0_41():
    assert importlib.metadata.version("SQLAlchemy") == "2.0.41"


def test_chart_round_trip_and_updates():
    store = LedgerStore()
    assert store.save_chart(_chart()) == 9
    assert store.load_chart().to_list() == _chart().to_list()
    renamed = ChartOfAccounts([Account("1000", "Petty cash", AccountType.ASSET),
                               Account("1500", "Equipment", AccountType.ASSET)])
    assert store.save_chart(renamed) == 2
    chart = store.load_chart()
    assert len(chart) == 10
    assert chart.get("1000").name == "Petty cash"
    assert chart.get("6100").parent == "6000"


def test_entries_round_trip_exactly():
    store = _filled()
    assert _summary(store.load_entries()) == _summary(_entries())
    assert [e.entry_id for e in store.load_entries(start=date(2024, 3, 8))] == ["e-manama", "e-rent", "e-sale"]
    ledger = store.load_ledger()
    assert ledger.balance("1000").amount == Decimal("8849.49")
    assert ledger.balance("1300").amount == Decimal("125000")
    assert ledger.balance("1400").amount == Decimal("12.345")


def test_account_totals_in_sql():
    store = _filled()
    totals = store.account_totals()
    assert totals["1000"] == (Decimal("10099.99"), Decimal("1250.50"))
    assert totals["1300"] == (Decimal("125000"), Decimal("0"))
    assert totals["4300"] == (Decimal("0"), Decimal("12.345"))
    assert set(totals) == {"1000", "1300", "1400", "3000", "4000", "4200", "4300", "6100"}
    early = store.account_totals(as_of=date(2024, 3, 8))
    assert early["1000"] == (Decimal("10000.00"), Decimal("0"))
    assert "6100" not in early and "1400" in early


def test_delete_and_count():
    store = _filled()
    assert store.count_entries() == 5
    assert store.delete_entry("e-rent") is True
    assert store.delete_entry("e-rent") is False
    assert store.count_entries() == 4
    assert "6100" not in store.account_totals()
    assert [e.entry_id for e in store.load_entries()] == ["e-capital", "e-tokyo", "e-manama", "e-sale"]


def test_file_database_changes_are_durable(tmp_path):
    url = f"sqlite:///{tmp_path / 'books.db'}"
    first = _filled(url)
    assert first.delete_entry("e-tokyo")
    second = LedgerStore(url)
    assert second.count_entries() == 4
    assert [e.entry_id for e in second.load_entries()] == ["e-capital", "e-manama", "e-rent", "e-sale"]
    assert second.load_chart().to_list() == _chart().to_list()
    assert second.delete_entry("e-sale")
    assert LedgerStore(url).count_entries() == 3
