import random
from datetime import date
from decimal import Decimal

import pytest

from ledgerkit.accounts import Account, AccountType, ChartOfAccounts
from ledgerkit.journal import Ledger
from ledgerkit.money import Money, quantum


def amounts(money, ratios):
    return [share.amount for share in money.allocate(ratios)]


@pytest.mark.parametrize(("money", "ratios", "expected"), [
    (Money("100.00", "USD"), [1, 1, 1], ["33.34", "33.33", "33.33"]),
    (Money("2.00", "USD"), [1, 1, 1], ["0.67", "0.67", "0.66"]),
    (Money("0.05", "USD"), [1, 1], ["0.03", "0.02"]),
    (Money("0.04", "USD"), [1, 1, 1], ["0.02", "0.01", "0.01"]),
    (Money("10.00", "USD"), [3, 7, 1], ["2.73", "6.36", "0.91"]),
    (Money("1000", "JPY"), [1, 1, 1], ["334", "333", "333"]),
    (Money("1.000", "BHD"), [1, 2], ["0.333", "0.667"]),
    (Money("-100.00", "USD"), [1, 1, 1], ["-33.34", "-33.33", "-33.33"]),
    (Money("100.005", "USD"), [1, 1], ["50.00", "50.00"]),
    (Money("7.00", "EUR"), [0, 1, 0, 2], ["0.00", "2.33", "0.00", "4.67"]),
])
def test_documented_examples(money, ratios, expected):
    assert amounts(money, ratios) == [Decimal(e) for e in expected]


def test_shares_always_add_up_and_stay_close():
    rng = random.Random(20240131)
    for _ in range(300):
        currency = rng.choice(["USD", "JPY", "BHD"])
        q = quantum(currency)
        money = Money(Decimal(rng.randint(-10**6, 10**6)) * q, currency)
        ratios = [rng.randint(0, 9) for _ in range(rng.randint(1, 6))]
        if not any(ratios):
            ratios[0] = 1
        shares = money.allocate(ratios)
        assert sum(s.amount for s in shares) == money.amount
        for share, ratio in zip(shares, ratios):
            exact = money.amount * ratio / sum(ratios)
            assert abs(share.amount - exact) < q
            assert share.currency == currency


def test_ledger_allocation_balances():
    chart = ChartOfAccounts([Account("1000", "Cash", AccountType.ASSET), Account("6200", "Marketing", AccountType.EXPENSE),
                             Account("6210", "Marketing A", AccountType.EXPENSE),
                             Account("6220", "Marketing B", AccountType.EXPENSE),
                             Account("6230", "Marketing C", AccountType.EXPENSE)])
    ledger = Ledger(chart)
    entry = ledger.allocate(day=date(2024, 3, 31), description="Split marketing", source="6200",
                            targets={"6210": 1, "6220": 1, "6230": 1}, amount=Money("100.00", "USD"))
    assert [p.amount.amount for p in entry.postings] == [Decimal("33.34"), Decimal("33.33"), Decimal("33.33"),
                                                         Decimal("-100.00")]
    assert ledger.balance("6210") == Money("33.34", "USD")
    assert ledger.balance("6200") == Money("-100.00", "USD")
