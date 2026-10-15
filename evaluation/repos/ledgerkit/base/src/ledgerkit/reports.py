"""Trial balance, income statement and balance sheet, plus plain-text table rendering."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Iterable, Sequence

from ledgerkit.accounts import AccountType
from ledgerkit.errors import RateNotFoundError
from ledgerkit.journal import Ledger
from ledgerkit.money import Money, format_amount
from ledgerkit.rates import RateTable


@dataclass(frozen=True)
class TrialBalanceLine:
    code: str
    name: str
    debit: Decimal
    credit: Decimal


@dataclass
class TrialBalance:
    currency: str
    as_of: date | None
    lines: list[TrialBalanceLine] = field(default_factory=list)

    @property
    def total_debit(self) -> Decimal:
        return sum((line.debit for line in self.lines), Decimal(0))

    @property
    def total_credit(self) -> Decimal:
        return sum((line.credit for line in self.lines), Decimal(0))

    @property
    def is_balanced(self) -> bool:
        return self.total_debit == self.total_credit


def _translate(amount: Money, currency: str, rates: RateTable | None, on: date | None) -> Money:
    if amount.currency == currency:
        return amount
    if rates is None:
        raise RateNotFoundError(f"reporting {amount.currency} amounts in {currency} needs a rate table")
    return rates.convert(amount, currency, on)


def trial_balance(ledger: Ledger, *, as_of: date | None = None, currency: str = "USD",
                  rates: RateTable | None = None) -> TrialBalance:
    """Net debit or credit balance of every account with activity up to and including ``as_of``; accounts
    kept in another currency are translated into ``currency`` at the rate on ``as_of``."""
    report = TrialBalance(currency, as_of)
    for account in ledger.chart:
        debits, credits = ledger.totals(account.code, None, as_of)
        if debits != credits:
            net = _translate(Money(debits - credits, account.currency), currency, rates, as_of).amount
            report.lines.append(TrialBalanceLine(account.code, account.name, max(net, Decimal(0)), max(-net, Decimal(0))))
    return report


def _section(ledger: Ledger, types: Iterable[AccountType], start: date | None, end: date | None, currency: str,
             rates: RateTable | None) -> dict[str, Decimal]:
    balances = ledger.balances(start, end, types).items()
    return {code: _translate(b, currency, rates, end).amount for code, b in balances if not b.is_zero()}


def income_statement(ledger: Ledger, start: date, end: date, *, currency: str = "USD",
                     rates: RateTable | None = None) -> dict[str, Any]:
    """Income and expense account balances for ``start``..``end`` (inclusive) and the net income."""
    income = _section(ledger, [AccountType.INCOME], start, end, currency, rates)
    expenses = _section(ledger, [AccountType.EXPENSE], start, end, currency, rates)
    total_income, total_expenses = sum(income.values(), Decimal(0)), sum(expenses.values(), Decimal(0))
    return {"currency": currency, "income": income, "expenses": expenses, "total_income": total_income,
            "total_expenses": total_expenses, "net_income": total_income - total_expenses}


def balance_sheet(ledger: Ledger, as_of: date, *, currency: str = "USD", rates: RateTable | None = None) -> dict[str, Any]:
    """Assets, liabilities and equity at ``as_of``; net income not yet closed is reported as current earnings."""
    sheet: dict[str, Any] = {"currency": currency}
    for key, account_type in (("assets", AccountType.ASSET), ("liabilities", AccountType.LIABILITY),
                              ("equity", AccountType.EQUITY)):
        sheet[key] = _section(ledger, [account_type], None, as_of, currency, rates)
        sheet[f"total_{key}"] = sum(sheet[key].values(), Decimal(0))
    sheet["current_earnings"] = income_statement(ledger, date.min, as_of, currency=currency, rates=rates)["net_income"]
    sheet["total_equity"] += sheet["current_earnings"]
    sheet["balanced"] = sheet["total_assets"] == sheet["total_liabilities"] + sheet["total_equity"]
    return sheet


def render_table(headers: Sequence[str], rows: Sequence[Sequence[Any]], width: int | None = None) -> str:
    """Render an aligned text table (numbers right-aligned); lines are cut to ``width`` characters."""
    text = [[format_amount(v) if isinstance(v, Decimal) else str(v) for v in row] for row in [headers, *rows]]
    widths = [max(len(r[i]) for r in text) for i in range(len(headers))]
    numeric = [any(isinstance(r[i], Decimal) for r in rows) for i in range(len(headers))]
    text.insert(1, ["-" * w for w in widths])
    lines = ["  ".join(c.rjust(w) if n else c.ljust(w) for c, w, n in zip(r, widths, numeric)).rstrip() for r in text]
    return "\n".join(line if width is None or len(line) <= width else line[: width - 1] + "…" for line in lines)
