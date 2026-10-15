from decimal import Decimal

import pytest

from ledgerkit.accounts import Account, AccountType, ChartOfAccounts
from ledgerkit.errors import AccountNotFoundError, DuplicateAccountError


def test_normal_balance_direction():
    cash = Account("1000", "Cash", AccountType.ASSET)
    sales = Account("4000", "Sales", AccountType.INCOME)
    assert cash.natural_balance(Decimal(100), Decimal(30)) == Decimal(70)
    assert sales.natural_balance(Decimal(10), Decimal(250)) == Decimal(240)
    assert AccountType.EXPENSE.debit_normal and not AccountType.LIABILITY.debit_normal


def test_chart_lookup_and_ordering(chart):
    assert [a.code for a in chart][:3] == ["1000", "1100", "1200"]
    assert chart.get("6100").parent == "6000"
    assert "9999" not in chart
    with pytest.raises(AccountNotFoundError) as info:
        chart.get("9999")
    assert str(info.value) == "no account with code '9999'"
    with pytest.raises(DuplicateAccountError):
        chart.add(Account("1000", "Cash again", AccountType.ASSET))


def test_chart_round_trip_resolves_parent_order(chart):
    rows = list(reversed(chart.to_list()))
    rebuilt = ChartOfAccounts.from_list(rows)
    assert rebuilt.to_list() == chart.to_list()
    with pytest.raises(AccountNotFoundError):
        ChartOfAccounts.from_list([{"code": "6100", "name": "Rent", "type": "expense", "parent": "6000"}])
