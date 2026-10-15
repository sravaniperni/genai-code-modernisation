from datetime import date
from decimal import Decimal

from ledgerkit.accounts import Account, AccountType, ChartOfAccounts
from ledgerkit.journal import JournalEntry, Ledger, Posting
from ledgerkit.periods import FiscalCalendar, close_period
from ledgerkit.reports import balance_sheet, income_statement, trial_balance


def _ledger() -> Ledger:
    ledger = Ledger(ChartOfAccounts([
        Account("1000", "Bank", AccountType.ASSET), Account("3000", "Capital", AccountType.EQUITY),
        Account("3100", "Retained Earnings", AccountType.EQUITY), Account("4000", "Sales", AccountType.INCOME),
        Account("6100", "Rent", AccountType.EXPENSE),
    ]))
    ledger.post(JournalEntry(date(2024, 3, 1), "Capital", (Posting.debit("1000", "5000"), Posting.credit("3000", "5000"))))
    ledger.post(JournalEntry(date(2024, 3, 1), "Rent", (Posting.debit("6100", "800"), Posting.credit("1000", "800"))))
    ledger.post(JournalEntry(date(2024, 3, 31), "Month-end sale", (Posting.debit("1000", "1000.00"),
                                                                   Posting.credit("4000", "1000.00"))))
    ledger.post(JournalEntry(date(2024, 4, 1), "April sale", (Posting.debit("1000", "250"), Posting.credit("4000", "250"))))
    return ledger


def test_entries_between_includes_both_bounds():
    ledger = _ledger()
    assert [e.description for e in ledger.entries_between(date(2024, 3, 1), date(2024, 3, 31))] == \
        ["Capital", "Rent", "Month-end sale"]
    assert [e.description for e in ledger.entries_between(date(2024, 3, 31), date(2024, 3, 31))] == ["Month-end sale"]
    assert [e.description for e in ledger.entries_between(end=date(2024, 3, 1))] == ["Capital", "Rent"]
    assert [e.description for e in ledger.entries_between(start=date(2024, 4, 1))] == ["April sale"]


def test_balances_and_reports_at_month_end():
    ledger = _ledger()
    assert ledger.balance("4000", end=date(2024, 3, 31)).amount == Decimal("1000.00")
    assert ledger.balance("1000", end=date(2024, 3, 31)).amount == Decimal("5200.00")
    assert ledger.totals("4000", date(2024, 3, 31), date(2024, 3, 31)) == (Decimal(0), Decimal("1000.00"))
    report = trial_balance(ledger, as_of=date(2024, 3, 31))
    assert {line.code: line.credit for line in report.lines}["4000"] == Decimal("1000.00")
    assert report.total_debit == Decimal("6000.00") and report.is_balanced
    statement = income_statement(ledger, date(2024, 3, 1), date(2024, 3, 31))
    assert statement["income"] == {"4000": Decimal("1000.00")}
    assert statement["net_income"] == Decimal("200.00")
    sheet = balance_sheet(ledger, date(2024, 3, 31))
    assert sheet["assets"] == {"1000": Decimal("5200.00")}
    assert sheet["current_earnings"] == Decimal("200.00") and sheet["balanced"]


def test_closing_includes_month_end_entries():
    ledger = _ledger()
    march = FiscalCalendar().period_for(date(2024, 3, 15))
    close_period(ledger, march, "3100")
    assert ledger.balance("4000", end=date(2024, 3, 31)).amount == 0
    assert ledger.balance("3100").amount == Decimal("200.00")
    assert ledger.balance("4000").amount == Decimal("250")
