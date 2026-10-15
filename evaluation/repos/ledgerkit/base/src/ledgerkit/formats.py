"""Versioned JSON interchange format for complete ledgers (chart of accounts + journal).

Postings without a ``currency`` use the document's ``currency``; unknown keys are ignored so that
documents written by newer minor versions remain readable.
"""

from __future__ import annotations

import json
from typing import Any

from marshmallow import EXCLUDE, Schema, ValidationError, fields, post_load, pre_dump, pre_load, validate, validates

from ledgerkit import versioning
from ledgerkit.accounts import AccountType, ChartOfAccounts
from ledgerkit.errors import FormatError, LedgerError
from ledgerkit.journal import JournalEntry, Ledger, Posting, format_timestamp, parse_timestamp
from ledgerkit.money import CURRENCIES, Money


class _Base(Schema):
    class Meta:
        unknown = EXCLUDE
        ordered = True


class PostingSchema(_Base):
    account = fields.Str(required=True, data_key="accountCode")
    amount = fields.Decimal(required=True, as_string=True)
    currency = fields.Str(missing=None)
    memo = fields.Str(missing="", default="")

    @pre_load(pass_many=False)
    def default_currency(self, data: Any, **kwargs: Any) -> Any:
        if isinstance(data, dict) and not data.get("currency"):
            data = {**data, "currency": self.context.get("currency", "USD")}
        return data

    @validates("currency")
    def check_currency(self, value: str) -> None:
        if value not in CURRENCIES:
            raise ValidationError(f"unknown currency {value!r}")

    @pre_dump
    def from_posting(self, p: Posting, **kwargs: Any) -> dict[str, Any]:
        return {"account": p.account, "amount": p.amount.amount, "currency": p.amount.currency, "memo": p.memo}

    @post_load
    def make_posting(self, data: dict[str, Any], **kwargs: Any) -> Posting:
        return Posting(data["account"], Money(data["amount"], data["currency"]), data["memo"])


class EntrySchema(_Base):
    id = fields.Str(required=True)
    date = fields.Date(required=True)
    description = fields.Str(required=True)
    reference = fields.Str(missing="", default="")
    created_at = fields.Str(required=True, data_key="createdAt")
    postings = fields.List(fields.Nested(PostingSchema), required=True, validate=validate.Length(min=2))

    @pre_dump
    def from_entry(self, e: JournalEntry, **kwargs: Any) -> dict[str, Any]:
        return {"id": e.entry_id, "date": e.date, "description": e.description, "reference": e.reference,
                "created_at": format_timestamp(e.created_at), "postings": list(e.postings)}

    @post_load
    def make_entry(self, data: dict[str, Any], **kwargs: Any) -> JournalEntry:
        try:
            created = parse_timestamp(data["created_at"])
        except ValueError:
            raise ValidationError("must look like 2024-01-31T10:00:00Z", "createdAt") from None
        return JournalEntry(data["date"], data["description"], tuple(data["postings"]), reference=data["reference"],
                            entry_id=data["id"], created_at=created)


class AccountSchema(_Base):
    code = fields.Str(required=True)
    name = fields.Str(required=True)
    type = fields.Str(required=True, validate=validate.OneOf([t.value for t in AccountType]))
    currency = fields.Str(missing="USD")
    parent = fields.Str(missing=None, allow_none=True)


class LedgerFileSchema(_Base):
    format_version = fields.Str(required=True, data_key="formatVersion")
    currency = fields.Str(missing="USD", default="USD")
    locked_through = fields.Date(missing=None, allow_none=True, data_key="lockedThrough")
    meta = fields.Field(missing=dict, default=dict, description="free-form metadata, preserved as is")
    accounts = fields.List(fields.Nested(AccountSchema), required=True)
    entries = fields.List(fields.Nested(EntrySchema), missing=list)

    @validates("format_version")
    def check_format_version(self, value: str) -> None:
        try:
            versioning.check_format_version(value)
        except FormatError as exc:
            raise ValidationError(str(exc)) from None


def _messages(errors: Any, prefix: str = "") -> list[str]:
    if not isinstance(errors, dict):
        return [f"{prefix.rstrip('.')}: {message}" for message in errors]
    return [m for key, value in errors.items() for m in _messages(value, f"{prefix}{key}.")]


def load_ledger(text: str) -> tuple[Ledger, dict[str, Any]]:
    """Parse a ledger document; returns the ledger and the document's ``meta`` mapping."""
    try:
        raw = json.loads(text)
    except ValueError as exc:
        raise FormatError(f"not valid JSON: {exc}") from None
    if not isinstance(raw, dict):
        raise FormatError("a ledger document must be a JSON object")
    try:
        data = LedgerFileSchema(context={"currency": raw.get("currency") or "USD"}).load(raw)
    except ValidationError as exc:
        raise FormatError("; ".join(sorted(_messages(exc.messages)))) from None
    try:
        ledger = Ledger(ChartOfAccounts.from_list(data["accounts"]))
        ledger.post_many(data["entries"])
    except LedgerError as exc:
        raise FormatError(f"inconsistent ledger document: {exc}") from None
    ledger.locked_through = data["locked_through"]
    return ledger, data["meta"]


def dump_ledger(ledger: Ledger, *, currency: str = "USD", meta: dict[str, Any] | None = None) -> str:
    document = {"format_version": versioning.FORMAT_VERSION, "currency": currency, "meta": meta or {},
                "locked_through": ledger.locked_through, "accounts": ledger.chart.to_list(), "entries": ledger.entries}
    return json.dumps(LedgerFileSchema().dump(document), indent=2)
