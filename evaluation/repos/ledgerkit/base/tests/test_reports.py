from datetime import date
from decimal import Decimal

import pytest

from conftest import entry
from ledgerkit.errors import RateNotFoundError
from ledgerkit.journal import Posting
from ledgerkit.reports import balance_sheet, income_statement, render_table, trial_balance


def test_trial_balance_columns_and_totals(ledger):
    report = trial_balance(ledger)
    lines = {line.code: (line.debit, line.credit) for line in report.lines}
    assert lines["1000"] == (Decimal("9200"), Decimal(0))
    assert lines["3000"] == (Decimal(0), Decimal("10000"))
    assert lines["4000"] == (Decimal(0), Decimal("2900.00"))
    assert report.total_debit == report.total_credit == Decimal("12900.00")
    assert report.is_balanced


def test_trial_balance_as_of(ledger):
    report = trial_balance(ledger, as_of=date(2024, 1, 12))
    assert {line.code for line in report.lines} == {"1000", "1100", "3000", "4000"}


def test_foreign_currency_accounts_need_a_rate_table(ledger):
    ledger.post(entry(date(2024, 1, 21), "Export sale", Posting.debit("1200", "100", "EUR"),
                      Posting.credit("4100", "100", "EUR")))
    with pytest.raises(RateNotFoundError):
        trial_balance(ledger)
    assert trial_balance(ledger, as_of=date(2024, 1, 19)).is_balanced  # before the EUR sale


def test_income_statement(ledger):
    statement = income_statement(ledger, date(2024, 1, 1), date(2024, 1, 30))
    assert statement["income"] == {"4000": Decimal("2900.00")}
    assert statement["expenses"] == {"6100": Decimal("1200")}
    assert statement["net_income"] == Decimal("1700.00")


def test_balance_sheet_balances_with_current_earnings(ledger):
    ledger.post(entry(date(2024, 1, 25), "Supplier bill", Posting.debit("6200", "300"), Posting.credit("2000", "300")))
    sheet = balance_sheet(ledger, date(2024, 1, 30))
    assert sheet["total_assets"] == Decimal("11700.00")
    assert sheet["liabilities"] == {"2000": Decimal("300")}
    assert sheet["current_earnings"] == Decimal("1400.00")
    assert sheet["total_equity"] == Decimal("11400.00")
    assert sheet["balanced"]


def test_render_table_alignment_and_width():
    text = render_table(["code", "name", "amount"], [("1000", "Cash", Decimal("1234.5")), ("4000", "Sales", Decimal("-7"))])
    assert text.splitlines() == [
        "code  name     amount",
        "----  -----  --------",
        "1000  Cash   1,234.50",
        "4000  Sales     -7.00",
    ]
    assert all(len(line) <= 12 for line in render_table(["code", "name"], [("1000", "A very long name")], width=12).splitlines())
