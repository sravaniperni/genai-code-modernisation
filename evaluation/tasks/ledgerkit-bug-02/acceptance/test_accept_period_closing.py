from datetime import date
from decimal import Decimal

import pytest

from ledgerkit.accounts import Account, AccountType, ChartOfAccounts
from ledgerkit.journal import JournalEntry, Ledger, Posting
from ledgerkit.periods import FiscalCalendar, close_period
from ledgerkit.reports import balance_sheet, income_statement, trial_balance

CALENDAR = FiscalCalendar()


def _ledger() -> Ledger:
    ledger = Ledger(ChartOfAccounts([
        Account("1000", "Cash", AccountType.ASSET), Account("3000", "Capital", AccountType.EQUITY),
        Account("3100", "Retained Earnings", AccountType.EQUITY), Account("4000", "Sales", AccountType.INCOME),
        Account("4010", "Sales Returns", AccountType.INCOME), Account("6100", "Rent", AccountType.EXPENSE),
        Account("6200", "Salaries", AccountType.EXPENSE), Account("6300", "Travel", AccountType.EXPENSE),
    ]))
    ledger.post(JournalEntry(date(2024, 1, 2), "Capital", (Posting.debit("1000", "20000"), Posting.credit("3000", "20000"))))
    ledger.post(JournalEntry(date(2024, 1, 9), "Sales", (Posting.debit("1000", "5000.00"), Posting.credit("4000", "5000.00"))))
    ledger.post(JournalEntry(date(2024, 1, 20), "Rent", (Posting.debit("6100", "1200.00"), Posting.credit("1000", "1200.00"))))
    ledger.post(JournalEntry(date(2024, 1, 25), "Payroll", (Posting.debit("6200", "2000.00"), Posting.credit("1000", "2000.00"))))
    return ledger


def _amount(ledger, code):
    return ledger.balance(code).amount


def test_reported_example():
    ledger = _ledger()
    january = CALENDAR.period_for(date(2024, 1, 15))
    entry = close_period(ledger, january, "3100")
    assert entry.date == date(2024, 1, 31)
    for code in ("4000", "6100", "6200"):
        assert _amount(ledger, code) == 0, code
    assert _amount(ledger, "3100") == Decimal("1800.00")
    assert trial_balance(ledger).is_balanced
    statement = income_statement(ledger, date(2024, 1, 1), date(2024, 1, 31))
    assert statement["net_income"] == 0 and statement["income"] == {} and statement["expenses"] == {}
    sheet = balance_sheet(ledger, date(2024, 1, 31))
    assert sheet["balanced"] and sheet["current_earnings"] == 0
    assert sheet["equity"] == {"3000": Decimal("20000"), "3100": Decimal("1800.00")}


def test_net_loss_reduces_retained_earnings():
    ledger = _ledger()
    close_period(ledger, CALENDAR.period_for(date(2024, 1, 15)), "3100")
    ledger.post(JournalEntry(date(2024, 2, 3), "Small sale", (Posting.debit("1000", "300"), Posting.credit("4000", "300"))))
    ledger.post(JournalEntry(date(2024, 2, 4), "Trip", (Posting.debit("6300", "1000"), Posting.credit("1000", "1000"))))
    february = CALENDAR.period_for(date(2024, 2, 10))
    close_period(ledger, february, "3100")
    assert _amount(ledger, "4000") == 0 and _amount(ledger, "6300") == 0
    assert _amount(ledger, "3100") == Decimal("1100.00")
    assert ledger.balance("6100", start=february.start, end=february.end).amount == 0
    assert trial_balance(ledger).is_balanced


def test_income_account_with_debit_balance_is_credited():
    ledger = _ledger()
    ledger.post(JournalEntry(date(2024, 1, 28), "Refunds", (Posting.debit("4010", "400"), Posting.credit("1000", "400"))))
    entry = close_period(ledger, CALENDAR.period_for(date(2024, 1, 15)), "3100")
    lines = {p.account: p.amount.amount for p in entry.postings}
    assert lines["4010"] == Decimal("-400")
    assert lines["6100"] == Decimal("-1200.00") and lines["6200"] == Decimal("-2000.00")
    assert lines["4000"] == Decimal("5000.00")
    assert lines["3100"] == Decimal("-1400.00")
    assert _amount(ledger, "4010") == 0 and _amount(ledger, "3100") == Decimal("1400.00")


def test_pure_expense_period_and_empty_period():
    ledger = Ledger(ChartOfAccounts([Account("1000", "Cash", AccountType.ASSET),
                                     Account("3100", "Retained Earnings", AccountType.EQUITY),
                                     Account("6100", "Rent", AccountType.EXPENSE)]))
    ledger.post(JournalEntry(date(2024, 3, 1), "Rent", (Posting.debit("6100", "999.99"), Posting.credit("1000", "999.99"))))
    entry = close_period(ledger, CALENDAR.period_for(date(2024, 3, 1)), "3100")
    assert [(p.account, p.amount.amount) for p in entry.postings] == [("6100", Decimal("-999.99")),
                                                                    ("3100", Decimal("999.99"))]
    assert ledger.balance("3100").amount == Decimal("-999.99")
    assert close_period(ledger, CALENDAR.period_for(date(2024, 4, 1)), "3100") is None
    assert ledger.locked_through == date(2024, 4, 30)
