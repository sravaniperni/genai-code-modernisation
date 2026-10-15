"""Validation schemas for entries submitted through the HTTP API and import jobs."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any, List

from pydantic import BaseModel, Field, ValidationError, condecimal, constr, root_validator, validator

from ledgerkit.errors import FormatError
from ledgerkit.journal import JournalEntry, Posting
from ledgerkit.money import CURRENCIES, Money

CurrencyCode = constr(regex=r"^[A-Z]{3}$")
AccountCode = constr(regex=r"^[0-9]{3,6}$")
Amount = condecimal(ge=0, max_digits=18, decimal_places=6)


class PostingIn(BaseModel):
    account: AccountCode
    debit: Amount = Decimal(0)
    credit: Amount = Decimal(0)
    currency: CurrencyCode = "USD"
    memo: str = ""

    class Config:
        extra = "forbid"
        anystr_strip_whitespace = True

    @validator("currency")
    def known_currency(cls, value: str) -> str:
        if value not in CURRENCIES:
            raise ValueError(f"unsupported currency {value}")
        return value

    @root_validator
    def one_side(cls, values: dict[str, Any]) -> dict[str, Any]:
        debit, credit = values.get("debit"), values.get("credit")
        if debit is not None and credit is not None and (debit > 0) == (credit > 0):
            raise ValueError("exactly one of debit or credit must be greater than zero")
        return values

    def to_posting(self) -> Posting:
        return Posting(self.account, Money(self.debit - self.credit, self.currency), self.memo)


class EntryIn(BaseModel):
    date: dt.date
    description: constr(min_length=1, max_length=200)
    reference: str = ""
    postings: List[PostingIn] = Field(..., min_items=2)

    class Config:
        extra = "forbid"
        anystr_strip_whitespace = True

    @validator("postings")
    def balanced(cls, postings: List[PostingIn]) -> List[PostingIn]:
        sums: dict[str, Decimal] = {}
        for p in postings:
            sums[p.currency] = sums.get(p.currency, Decimal(0)) + p.debit - p.credit
        unbalanced = sorted(cur for cur, diff in sums.items() if diff != 0)
        if unbalanced:
            raise ValueError(f"entry does not balance in {', '.join(unbalanced)}")
        return postings

    def to_entry(self) -> JournalEntry:
        postings = tuple(p.to_posting() for p in self.postings)
        return JournalEntry(self.date, self.description, postings, reference=self.reference)

    @classmethod
    def from_entry(cls, entry: JournalEntry) -> EntryIn:
        postings = [PostingIn(account=p.account, debit=p.debit_amount, credit=p.credit_amount,
                              currency=p.amount.currency, memo=p.memo) for p in entry.postings]
        return cls(date=entry.date, description=entry.description, reference=entry.reference, postings=postings)


def describe_errors(exc: ValidationError) -> list[str]:
    """Flatten validation errors into ``"postings.0.debit: message"`` strings."""
    return [f"{'.'.join(str(part) for part in err['loc'])}: {err['msg']}" for err in exc.errors()]


def parse_entry(payload: dict[str, Any]) -> JournalEntry:
    """Validate an API payload and build the journal entry; raises :class:`FormatError` listing all problems."""
    try:
        return EntryIn.parse_obj(payload).to_entry()
    except ValidationError as exc:
        raise FormatError("; ".join(describe_errors(exc))) from None


def entry_payload(entry: JournalEntry) -> dict[str, Any]:
    """JSON-compatible API representation of ``entry`` (amounts and dates as strings)."""
    data = EntryIn.from_entry(entry).dict()
    data["date"] = data["date"].isoformat()
    data["postings"] = [{**p, "debit": str(p["debit"]), "credit": str(p["credit"])} for p in data["postings"]]
    return data
