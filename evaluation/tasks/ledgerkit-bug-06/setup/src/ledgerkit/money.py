"""Decimal money values, currency metadata and amount parsing/formatting."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_FLOOR, ROUND_HALF_EVEN, Decimal, InvalidOperation
from typing import Sequence

from ledgerkit.errors import CurrencyMismatchError, FormatError, UnknownCurrencyError

CURRENCIES = {"USD": 2, "EUR": 2, "GBP": 2, "CHF": 2, "SEK": 2, "CAD": 2, "INR": 2, "JPY": 0, "KRW": 0, "BHD": 3}


def minor_digits(currency: str) -> int:
    try:
        return CURRENCIES[currency]
    except KeyError:
        raise UnknownCurrencyError(f"unknown currency {currency!r}") from None


def quantum(currency: str) -> Decimal:  # smallest representable amount, e.g. Decimal("0.01") for USD
    return Decimal(1).scaleb(-minor_digits(currency))


def to_decimal(value: object) -> Decimal:
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(repr(value) if isinstance(value, float) else str(value))
    except InvalidOperation:
        raise FormatError(f"not a decimal amount: {value!r}") from None


@dataclass(frozen=True)
class Money:
    amount: Decimal
    currency: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "amount", to_decimal(self.amount))
        minor_digits(self.currency)

    def _same(self, other: Money) -> Money:
        if not isinstance(other, Money):
            raise TypeError(f"expected Money, got {type(other).__name__}")
        if other.currency != self.currency:
            raise CurrencyMismatchError(f"{self.currency} vs {other.currency}")
        return other

    def __add__(self, other: Money) -> Money:
        return Money(self.amount + self._same(other).amount, self.currency)

    def __sub__(self, other: Money) -> Money:
        return Money(self.amount - self._same(other).amount, self.currency)

    def __neg__(self) -> Money:
        return Money(-self.amount, self.currency)

    def __abs__(self) -> Money:
        return Money(abs(self.amount), self.currency)

    def is_zero(self) -> bool:
        return self.amount == 0

    def rounded(self) -> Money:
        """Quantize to the currency's minor unit using banker's rounding."""
        return Money(self.amount.quantize(quantum(self.currency), rounding=ROUND_HALF_EVEN), self.currency)

    def allocate(self, ratios: Sequence[int | Decimal]) -> list[Money]:
        """Split proportionally to ``ratios`` without losing or creating minor units: every share is its
        exact proportional share rounded down to the minor unit, then the leftover units go one each to
        the shares with the largest discarded remainders (earlier shares win ties)."""
        weights = [to_decimal(r) for r in ratios]
        if not weights or any(w < 0 for w in weights) or sum(weights) == 0:
            raise ValueError("ratios must be non-negative and not all zero")
        if self.amount < 0:
            return [-share for share in (-self).allocate(weights)]
        q = quantum(self.currency)
        units = int(self.rounded().amount / q)
        exact = [units * w / sum(weights) for w in weights]
        shares = [int(e.to_integral_value(rounding=ROUND_FLOOR)) for e in exact]
        order = sorted(range(len(exact)), key=lambda i: (shares[i] - exact[i], i))
        for i in order[: units - sum(shares)]:
            shares[i] += 1
        return [Money(share * q, self.currency) for share in shares]

    def __str__(self) -> str:
        return f"{format_amount(self.amount, minor_digits(self.currency))} {self.currency}"


def parse_amount(text: str, decimal_sep: str = ".", thousands_sep: str = ",") -> Decimal:
    """Parse a human-entered amount such as ``"1,234.56"``, ``"(12.00)"`` or ``"1.234,56"`` (with
    ``decimal_sep=","`` and ``thousands_sep="."``). Parentheses or a minus sign mark negative amounts."""
    raw = text.strip().strip("$€£¥").strip()
    negative = False
    if raw.startswith("(") and raw.endswith(")"):
        negative, raw = True, raw[1:-1].strip()
    if raw.endswith("-") or raw.startswith("-"):
        negative, raw = not negative, raw.strip("-")
    if not raw:
        raise FormatError(f"not an amount: {text!r}")
    if decimal_sep != ".":
        raw = raw.replace(decimal_sep, ".")
    if thousands_sep:
        raw = raw.replace(thousands_sep, "")
    value = to_decimal(raw.replace(" ", ""))
    return -value if negative else value


def format_amount(value: Decimal, places: int = 2) -> str:
    """Format with thousands separators and a fixed number of decimal places."""
    return f"{to_decimal(value).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_EVEN):,.{places}f}"
