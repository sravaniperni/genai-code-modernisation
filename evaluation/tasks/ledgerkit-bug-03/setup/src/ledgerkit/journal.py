"""Journal entries, postings and the in-memory ledger."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Iterable, Mapping

from ledgerkit.accounts import AccountType, ChartOfAccounts
from ledgerkit.errors import CurrencyMismatchError, PeriodClosedError, UnbalancedEntryError
from ledgerkit.money import Money, quantum

TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def utcnow() -> datetime:
    """Current time in UTC; used to stamp newly created entries."""
    return datetime.utcnow()


def from_timestamp(ts: float) -> datetime:
    """UTC datetime for a POSIX timestamp (bank feeds deliver epoch seconds)."""
    return datetime.utcfromtimestamp(ts)


def format_timestamp(value: datetime) -> str:
    """Serialise a UTC timestamp as ``2024-01-31T10:00:00Z`` (whole seconds)."""
    return value.strftime(TIMESTAMP_FORMAT)


def parse_timestamp(text: str) -> datetime:
    return datetime.strptime(text, TIMESTAMP_FORMAT)


@dataclass(frozen=True)
class Posting:
    """One line of an entry. Positive amounts are debits, negative amounts are credits."""

    account: str
    amount: Money
    memo: str = ""

    @classmethod
    def debit(cls, account: str, amount: Decimal | int | str, currency: str = "USD", memo: str = "") -> Posting:
        return cls(account, abs(Money(amount, currency)), memo)

    @classmethod
    def credit(cls, account: str, amount: Decimal | int | str, currency: str = "USD", memo: str = "") -> Posting:
        return cls(account, -abs(Money(amount, currency)), memo)

    @property
    def debit_amount(self) -> Decimal:
        return max(self.amount.amount, Decimal(0))

    @property
    def credit_amount(self) -> Decimal:
        return max(-self.amount.amount, Decimal(0))


@dataclass
class JournalEntry:
    date: date
    description: str
    postings: tuple[Posting, ...]
    reference: str = ""
    entry_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    created_at: datetime = field(default_factory=utcnow)

    def __post_init__(self) -> None:
        self.postings = tuple(self.postings)

    def totals(self) -> dict[str, tuple[Decimal, Decimal]]:
        out: dict[str, tuple[Decimal, Decimal]] = {}
        for p in self.postings:
            debits, credits = out.get(p.amount.currency, (Decimal(0), Decimal(0)))
            out[p.amount.currency] = (debits + p.debit_amount, credits + p.credit_amount)
        return out

    def validate(self) -> None:
        """Raise :class:`UnbalancedEntryError` unless debits equal credits in every currency. Differences
        below half a minor unit (conversion noise) are tolerated; anything that shows up as a cent is not."""
        if len(self.postings) < 2:
            raise UnbalancedEntryError("an entry needs at least two postings")
        if any(p.amount.is_zero() for p in self.postings):
            raise UnbalancedEntryError("postings must not be zero")
        for currency, (debits, credits) in self.totals().items():
            if abs(debits - credits) >= quantum(currency) / 2:
                raise UnbalancedEntryError(f"entry {self.reference or self.entry_id} does not balance in {currency}: "
                                           f"debits {debits} != credits {credits}")

    def to_dict(self) -> dict[str, Any]:
        postings = [{"account": p.account, "amount": str(p.amount.amount), "currency": p.amount.currency,
                     "memo": p.memo} for p in self.postings]
        return {"id": self.entry_id, "date": self.date.isoformat(), "description": self.description,
                "reference": self.reference, "created_at": format_timestamp(self.created_at), "postings": postings}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> JournalEntry:
        postings = [Posting(p["account"], Money(p["amount"], p["currency"]), p.get("memo", "")) for p in data["postings"]]
        return cls(date.fromisoformat(data["date"]), data["description"], tuple(postings),
                   reference=data.get("reference", ""), entry_id=data["id"],
                   created_at=parse_timestamp(data["created_at"]))


class Ledger:
    """Validated journal entries posted against a chart of accounts; ``audit`` is an optional
    :class:`ledgerkit.audit.AuditLog`-like sink notified of every posting."""

    def __init__(self, chart: ChartOfAccounts, *, audit: Any = None):
        self.chart = chart
        self.audit = audit
        self.locked_through: date | None = None
        self._entries: list[JournalEntry] = []

    def post(self, entry: JournalEntry) -> JournalEntry:
        entry.validate()
        for p in entry.postings:
            account = self.chart.get(p.account)
            if account.currency != p.amount.currency:
                raise CurrencyMismatchError(f"account {account.code} is kept in {account.currency}, not {p.amount.currency}")
        if self.locked_through is not None and entry.date <= self.locked_through:
            raise PeriodClosedError(f"books are closed through {self.locked_through.isoformat()}")
        self._entries.append(entry)
        if self.audit is not None:
            self.audit.record("post", day=entry.date, entry_id=entry.entry_id, detail=entry.description)
        return entry

    def post_many(self, entries: Iterable[JournalEntry]) -> list[JournalEntry]:
        return [self.post(entry) for entry in entries]

    @property
    def entries(self) -> list[JournalEntry]:
        return sorted(self._entries, key=lambda e: e.date)

    def entries_between(self, start: date | None = None, end: date | None = None) -> list[JournalEntry]:
        """Entries dated from ``start`` to ``end``; both bounds are optional and inclusive."""
        return [e for e in self.entries if (start is None or e.date >= start) and (end is None or e.date < end)]

    def totals(self, code: str, start: date | None = None, end: date | None = None) -> tuple[Decimal, Decimal]:
        debits = credits = Decimal(0)
        for entry in self.entries_between(start, end):
            for p in entry.postings:
                if p.account == code:
                    debits, credits = debits + p.debit_amount, credits + p.credit_amount
        return debits, credits

    def balance(self, code: str, start: date | None = None, end: date | None = None) -> Money:
        """Natural-sign balance of one account (positive when it has its normal balance)."""
        account = self.chart.get(code)
        return Money(account.natural_balance(*self.totals(code, start, end)), account.currency)

    def balances(self, start: date | None = None, end: date | None = None,
                 types: Iterable[AccountType] | None = None) -> dict[str, Money]:
        wanted = set(types) if types is not None else set(AccountType)
        return {a.code: self.balance(a.code, start, end) for a in self.chart if a.type in wanted}

    def allocate(self, *, day: date, description: str, source: str, targets: Mapping[str, int | Decimal],
                 amount: Money) -> JournalEntry:
        """Post an entry moving ``amount`` out of ``source`` into ``targets`` in proportion to their weights."""
        shares = amount.allocate(list(targets.values()))
        postings = [Posting(code, share) for code, share in zip(targets, shares) if not share.is_zero()]
        postings.append(Posting(source, -amount.rounded()))
        return self.post(JournalEntry(day, description, tuple(postings), reference=f"ALLOC-{source}"))

    def to_dict(self) -> dict[str, Any]:
        return {"chart": self.chart.to_list(), "entries": [e.to_dict() for e in self.entries],
                "locked_through": self.locked_through.isoformat() if self.locked_through else None}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Ledger:
        ledger = cls(ChartOfAccounts.from_list(data["chart"]))
        ledger.post_many(JournalEntry.from_dict(e) for e in data["entries"])
        if data.get("locked_through"):
            ledger.locked_through = date.fromisoformat(data["locked_through"])
        return ledger
