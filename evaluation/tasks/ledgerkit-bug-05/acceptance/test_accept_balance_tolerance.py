from datetime import date
from decimal import Decimal

import pytest

from ledgerkit.accounts import Account, AccountType, ChartOfAccounts
from ledgerkit.errors import UnbalancedEntryError
from ledgerkit.journal import JournalEntry, Ledger, Posting
from ledgerkit.reports import trial_balance


def _ledger() -> Ledger:
    return Ledger(ChartOfAccounts([
        Account("1000", "Cash", AccountType.ASSET), Account("1300", "Cash JPY", AccountType.ASSET, "JPY"),
        Account("1400", "Cash BHD", AccountType.ASSET, "BHD"), Account("1200", "Cash EUR", AccountType.ASSET, "EUR"),
        Account("4000", "Sales", AccountType.INCOME), Account("4200", "Sales JPY", AccountType.INCOME, "JPY"),
        Account("4300", "Sales BHD", AccountType.INCOME, "BHD"), Account("4100", "Sales EUR", AccountType.INCOME, "EUR"),
    ]))


def _entry(*postings):
    return JournalEntry(date(2024, 6, 3), "test", postings)


@pytest.mark.parametrize(("debit", "credit"), [
    (Posting.debit("1000", "100.00"), Posting.credit("4000", "99.99")),
    (Posting.debit("1000", "99.99"), Posting.credit("4000", "100.00")),
    (Posting.debit("1300", "1000", "JPY"), Posting.credit("4200", "999", "JPY")),
    (Posting.debit("1400", "5.000", "BHD"), Posting.credit("4300", "4.999", "BHD")),
    (Posting.debit("1000", "10.006"), Posting.credit("4000", "10.00")),
])
def test_differences_visible_in_the_minor_unit_are_rejected(debit, credit):
    ledger = _ledger()
    entry = _entry(debit, credit)
    with pytest.raises(UnbalancedEntryError):
        entry.validate()
    with pytest.raises(UnbalancedEntryError):
        ledger.post(entry)
    assert ledger.entries == []


def test_each_currency_must_balance_on_its_own():
    ledger = _ledger()
    with pytest.raises(UnbalancedEntryError):
        ledger.post(_entry(Posting.debit("1000", "50.00"), Posting.credit("4000", "50.00"),
                           Posting.debit("1200", "20.00", "EUR"), Posting.credit("4100", "19.99", "EUR")))
    ledger.post(_entry(Posting.debit("1000", "50.00"), Posting.credit("4000", "50.00"),
                       Posting.debit("1200", "20.00", "EUR"), Posting.credit("4100", "20.00", "EUR")))
    assert len(ledger.entries) == 1


def test_sub_minor_unit_noise_is_tolerated():
    ledger = _ledger()
    ledger.post(_entry(Posting.debit("1000", "33.333"), Posting.credit("4000", "33.33")))
    ledger.post(_entry(Posting.debit("1300", "1000.4", "JPY"), Posting.credit("4200", "1000", "JPY")))
    ledger.post(_entry(Posting.debit("1000", "10.00"), Posting.credit("4000", "3.333"), Posting.credit("4000", "3.333"),
                       Posting.credit("4000", "3.333")))
    assert len(ledger.entries) == 3


def test_trial_balance_stays_balanced_after_rejections():
    ledger = _ledger()
    ledger.post(_entry(Posting.debit("1000", "250.00"), Posting.credit("4000", "250.00")))
    for credit in ("249.99", "250.01"):
        with pytest.raises(UnbalancedEntryError):
            ledger.post(_entry(Posting.debit("1000", "250.00"), Posting.credit("4000", credit)))
    report = trial_balance(ledger)
    assert report.total_debit == report.total_credit == Decimal("250.00")
