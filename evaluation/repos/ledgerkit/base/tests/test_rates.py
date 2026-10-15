from datetime import date
from decimal import Decimal

import pytest

from ledgerkit.errors import RateNotFoundError
from ledgerkit.money import Money
from ledgerkit.rates import Rate, RateRefresher, RateTable


@pytest.fixture
def table():
    t = RateTable()
    t.add("EUR", "USD", "1.10", date(2024, 1, 1))
    t.add("EUR", "USD", "1.20", date(2024, 3, 1))
    t.add("GBP", "EUR", "1.25", date(2024, 1, 1))
    return t


def test_rate_lookup_by_date_and_inverse(table):
    assert table.rate("EUR", "USD", date(2024, 2, 1)) == Decimal("1.10")
    assert table.rate("EUR", "USD", date(2024, 3, 5)) == Decimal("1.20")
    assert table.rate("EUR", "USD") == Decimal("1.20")
    assert table.rate("EUR", "GBP", date(2024, 1, 3)) == Decimal("0.8")
    assert table.rate("JPY", "JPY") == 1


def test_missing_rates(table):
    with pytest.raises(RateNotFoundError):
        table.rate("USD", "JPY")
    with pytest.raises(RateNotFoundError):
        table.rate("EUR", "USD", date(2023, 12, 31))
    with pytest.raises(ValueError):
        table.add("EUR", "USD", "0", date(2024, 1, 1))


def test_convert_same_currency_is_identity(table):
    assert table.convert(Money("12.345", "USD"), "USD") == Money("12.345", "USD")


def test_refresher_loads_rates_in_background():
    table = RateTable()
    refresher = RateRefresher(table, lambda: [Rate("USD", "CHF", Decimal("0.9"), date(2024, 1, 1))], interval=3600)
    refresher.start()
    try:
        assert refresher.wait_for_refresh(timeout=5)
        assert refresher.running
    finally:
        refresher.stop()
    assert not refresher.running
    assert table.rate("USD", "CHF") == Decimal("0.9")
