"""Accounts and the chart of accounts."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Any, Iterable, Iterator

from ledgerkit.errors import AccountNotFoundError, DuplicateAccountError
from ledgerkit.money import minor_digits


class AccountType(str, Enum):
    ASSET = "asset"
    LIABILITY = "liability"
    EQUITY = "equity"
    INCOME = "income"
    EXPENSE = "expense"

    @property
    def debit_normal(self) -> bool:
        """Assets and expenses increase with debits; liabilities, equity and income with credits."""
        return self in (AccountType.ASSET, AccountType.EXPENSE)


@dataclass(frozen=True)
class Account:
    code: str
    name: str
    type: AccountType
    currency: str = "USD"
    parent: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "type", AccountType(self.type))
        minor_digits(self.currency)

    def natural_balance(self, debits: Decimal, credits: Decimal) -> Decimal:
        """Balance in the account's normal direction (positive when it has its normal balance)."""
        return debits - credits if self.type.debit_normal else credits - debits

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "name": self.name, "type": self.type.value, "currency": self.currency,
                "parent": self.parent}


class ChartOfAccounts:
    """Accounts addressed by code; iteration is ordered by code."""

    def __init__(self, accounts: Iterable[Account] = ()):
        self._accounts: dict[str, Account] = {}
        for account in accounts:
            self.add(account)

    def add(self, account: Account) -> Account:
        if account.code in self._accounts:
            raise DuplicateAccountError(f"account {account.code} already exists")
        if account.parent is not None and account.parent not in self._accounts:
            raise AccountNotFoundError(f"parent account {account.parent} of {account.code} does not exist")
        self._accounts[account.code] = account
        return account

    def get(self, code: str) -> Account:
        try:
            return self._accounts[code]
        except KeyError:
            raise AccountNotFoundError(f"no account with code {code!r}") from None

    def __contains__(self, code: object) -> bool:
        return code in self._accounts

    def __iter__(self) -> Iterator[Account]:
        return iter(sorted(self._accounts.values(), key=lambda a: a.code))

    def __len__(self) -> int:
        return len(self._accounts)

    def to_list(self) -> list[dict[str, Any]]:
        return [a.to_dict() for a in self]

    @classmethod
    def from_list(cls, rows: Iterable[dict[str, Any]]) -> ChartOfAccounts:
        """Build a chart from ``to_list()``-style rows; parents may appear after their children."""
        pending, chart = [dict(r) for r in rows], cls()
        while pending:
            ready = [r for r in pending if not r.get("parent") or r["parent"] in chart]
            if not ready:
                raise AccountNotFoundError(f"unresolvable parent accounts: {sorted(r['code'] for r in pending)}")
            for row in ready:
                chart.add(Account(row["code"], row["name"], row["type"], row.get("currency") or "USD",
                                  row.get("parent") or None))
                pending.remove(row)
        return chart
