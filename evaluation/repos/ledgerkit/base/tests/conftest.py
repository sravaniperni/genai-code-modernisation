from datetime import date

import pytest

from ledgerkit.accounts import Account, AccountType, ChartOfAccounts
from ledgerkit.journal import JournalEntry, Ledger, Posting


def make_chart() -> ChartOfAccounts:
    return ChartOfAccounts([
        Account("1000", "Cash", AccountType.ASSET),
        Account("1100", "Accounts Receivable", AccountType.ASSET),
        Account("1200", "Bank EUR", AccountType.ASSET, "EUR"),
        Account("2000", "Accounts Payable", AccountType.LIABILITY),
        Account("3000", "Owner's Capital", AccountType.EQUITY),
        Account("3100", "Retained Earnings", AccountType.EQUITY),
        Account("4000", "Sales", AccountType.INCOME),
        Account("4100", "Export Sales", AccountType.INCOME, "EUR"),
        Account("6000", "Operating Expenses", AccountType.EXPENSE),
        Account("6100", "Rent", AccountType.EXPENSE, parent="6000"),
        Account("6200", "Marketing", AccountType.EXPENSE, parent="6000"),
    ])


def entry(day: date, description: str, *postings: Posting, reference: str = "") -> JournalEntry:
    return JournalEntry(day, description, postings, reference=reference)


@pytest.fixture
def chart() -> ChartOfAccounts:
    return make_chart()


@pytest.fixture
def ledger(chart: ChartOfAccounts) -> Ledger:
    """Capital, two sales and rent in January 2024 (no entry on a month end)."""
    led = Ledger(chart)
    led.post(entry(date(2024, 1, 2), "Owner investment", Posting.debit("1000", "10000"), Posting.credit("3000", "10000")))
    led.post(entry(date(2024, 1, 10), "Invoice 1", Posting.debit("1100", "2500.00"), Posting.credit("4000", "2500.00")))
    led.post(entry(date(2024, 1, 15), "Cash sale", Posting.debit("1000", "400"), Posting.credit("4000", "400")))
    led.post(entry(date(2024, 1, 20), "January rent", Posting.debit("6100", "1200"), Posting.credit("1000", "1200")))
    return led
