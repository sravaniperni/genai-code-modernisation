from datetime import date
from decimal import Decimal

import pytest

from ledgerkit.accounts import Account, AccountType, ChartOfAccounts
from ledgerkit.journal import JournalEntry, Ledger, Posting
from ledgerkit.money import Money
from ledgerkit.rates import RateTable
from ledgerkit.reports import income_statement, trial_balance


@pytest.fixture
def table():
    t = RateTable(max_age_days=400)
    t.add("EUR", "USD", "1.10", date(2024, 1, 1))
    t.add("EUR", "USD", "1.20", date(2024, 3, 1))
    t.add("USD", "JPY", "151.37", date(2024, 1, 1))
    t.add("BHD", "USD", "2.65", date(2024, 1, 1))
    return t


def test_reported_example():
    table = RateTable()
    table.add("EUR", "USD", "1.10", date(2024, 1, 1))
    assert table.convert(Money("100.00", "EUR"), "USD") == Money("110.00", "USD")
    assert table.convert(Money("110.00", "USD"), "EUR") == Money("100.00", "EUR")


def test_direct_and_inverse_pairs_with_rounding(table):
    assert table.convert(Money("25.00", "USD"), "JPY", date(2024, 2, 1)) == Money("3784", "JPY")
    assert table.convert(Money("10000", "JPY"), "USD", date(2024, 2, 1)) == Money("66.06", "USD")
    assert table.convert(Money("1.000", "BHD"), "USD", date(2024, 2, 1)) == Money("2.65", "USD")
    assert table.convert(Money("100.00", "USD"), "BHD", date(2024, 2, 1)) == Money("37.736", "BHD")


def test_conversion_uses_rate_on_or_before_date(table):
    assert table.convert(Money("50.00", "EUR"), "USD", date(2024, 2, 29)) == Money("55.00", "USD")
    assert table.convert(Money("50.00", "EUR"), "USD", date(2024, 3, 1)) == Money("60.00", "USD")
    assert table.convert(Money("60.00", "USD"), "EUR", date(2024, 3, 5)) == Money("50.00", "EUR")


def test_round_trips_stay_close(table):
    for amount in ("0.01", "19.99", "1234.56", "99999.99"):
        usd = table.convert(Money(amount, "EUR"), "USD", date(2024, 2, 1))
        back = table.convert(usd, "EUR", date(2024, 2, 1))
        assert abs(back.amount - Decimal(amount)) <= Decimal("0.01")
        assert usd.amount > Decimal(amount) or Decimal(amount) == Decimal("0.01")


def test_reports_translate_foreign_accounts(table):
    ledger = Ledger(ChartOfAccounts([
        Account("1000", "Bank USD", AccountType.ASSET), Account("1200", "Bank EUR", AccountType.ASSET, "EUR"),
        Account("3000", "Capital", AccountType.EQUITY), Account("4100", "Export Sales", AccountType.INCOME, "EUR"),
    ]))
    ledger.post(JournalEntry(date(2024, 2, 1), "Capital", (Posting.debit("1000", "1000"), Posting.credit("3000", "1000"))))
    ledger.post(JournalEntry(date(2024, 2, 10), "Export", (Posting.debit("1200", "500.00", "EUR"),
                                                          Posting.credit("4100", "500.00", "EUR"))))
    report = trial_balance(ledger, as_of=date(2024, 2, 20), currency="USD", rates=table)
    lines = {line.code: (line.debit, line.credit) for line in report.lines}
    assert lines["1200"] == (Decimal("550.00"), Decimal(0))
    assert lines["4100"] == (Decimal(0), Decimal("550.00"))
    assert report.is_balanced
    statement = income_statement(ledger, date(2024, 2, 1), date(2024, 2, 29), currency="EUR", rates=table)
    assert statement["income"] == {"4100": Decimal("500.00")}
