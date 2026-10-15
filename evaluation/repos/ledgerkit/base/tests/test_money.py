from decimal import Decimal

import pytest

from ledgerkit.errors import CurrencyMismatchError, FormatError, UnknownCurrencyError
from ledgerkit.money import Money, format_amount, parse_amount, quantum


def test_money_arithmetic_and_currency_checks():
    assert Money("10.50", "USD") + Money("0.25", "USD") == Money(Decimal("10.75"), "USD")
    assert -Money("3", "EUR") == Money("-3", "EUR")
    with pytest.raises(CurrencyMismatchError):
        Money("1", "USD") + Money("1", "EUR")
    with pytest.raises(UnknownCurrencyError):
        Money("1", "XXX")


def test_rounding_uses_currency_minor_units():
    assert Money("2.675", "USD").rounded().amount == Decimal("2.68")
    assert Money("2.665", "USD").rounded().amount == Decimal("2.66")
    assert Money("1234.5", "JPY").rounded().amount == Decimal("1234")
    assert quantum("BHD") == Decimal("0.001")


def test_allocate_even_splits():
    cases = [(Money("100.00", "USD"), [1, 1], ["50.00", "50.00"]), (Money("100.00", "USD"), [1, 3], ["25.00", "75.00"]),
             (Money("-60.00", "USD"), [2, 1], ["-40.00", "-20.00"]), (Money("90", "JPY"), [1, 0, 2], ["30", "0", "60"])]
    for money, ratios, expected in cases:
        assert [s.amount for s in money.allocate(ratios)] == [Decimal(e) for e in expected]


def test_allocate_rejects_bad_ratios():
    with pytest.raises(ValueError):
        Money("10", "USD").allocate([])
    with pytest.raises(ValueError):
        Money("10", "USD").allocate([0, 0])


def test_parse_amount_default_format():
    cases = {"1,234.56": "1234.56", "$ 12.00": "12.00", "(45.10)": "-45.10", "45.10-": "-45.10", "-7": "-7"}
    for text, expected in cases.items():
        assert parse_amount(text) == Decimal(expected), text


def test_parse_amount_rejects_garbage():
    with pytest.raises(FormatError):
        parse_amount("twelve")
    with pytest.raises(FormatError):
        parse_amount("  ")


def test_format_amount():
    assert format_amount(Decimal("1234567.891")) == "1,234,567.89"
    assert str(Money("1500", "JPY")) == "1,500 JPY"
