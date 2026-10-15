"""CSV and JSON-lines bank feed importers."""

from __future__ import annotations

import csv
import io
import json
import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Iterable, TextIO

from ledgerkit.errors import FormatError
from ledgerkit.journal import JournalEntry, Posting, from_timestamp
from ledgerkit.money import Money, parse_amount, to_decimal

log = logging.getLogger(__name__)

CSV_COLUMNS = ["date", "reference", "description", "account", "debit", "credit", "currency"]


def read_csv(source: str | TextIO, *, decimal_sep: str = ".", thousands_sep: str = ",",
             default_currency: str = "USD", date_format: str = "%Y-%m-%d") -> list[JournalEntry]:
    """Read entries from CSV with the columns in :data:`CSV_COLUMNS`; rows sharing a ``reference`` form one
    entry. Blank rows and rows without an account are skipped with a warning. Amounts are parsed with
    :func:`ledgerkit.money.parse_amount` using the given separators."""
    stream = io.StringIO(source) if isinstance(source, str) else source
    groups: dict[str, list[Posting]] = {}
    headers: dict[str, tuple[date, str]] = {}
    for lineno, row in enumerate(csv.DictReader(stream), start=2):
        if not any((value or "").strip() for value in row.values()):
            log.warning("skipping blank CSV row %d", lineno)
            continue
        account = (row.get("account") or "").strip()
        if not account:
            log.warning("skipping CSV row %d: no account given", lineno)
            continue
        try:
            day = datetime.strptime((row.get("date") or "").strip(), date_format).date()
            debit, credit = (parse_amount(row[c], decimal_sep, thousands_sep) if (row.get(c) or "").strip()
                             else Decimal(0) for c in ("debit", "credit"))
        except (ValueError, FormatError) as exc:
            raise FormatError(f"CSV line {lineno}: {exc}") from None
        reference = (row.get("reference") or "").strip() or f"row-{lineno}"
        currency = (row.get("currency") or "").strip() or default_currency
        groups.setdefault(reference, []).append(Posting(account, Money(debit - credit, currency)))
        headers.setdefault(reference, (day, (row.get("description") or "").strip()))
    return [JournalEntry(headers[ref][0], headers[ref][1], tuple(p), reference=ref) for ref, p in groups.items()]


def read_bank_feed(lines: Iterable[str], *, bank_account: str, suspense_account: str,
                   currency: str = "USD") -> list[JournalEntry]:
    """Turn JSON lines like ``{"id": "tx-1", "ts": 1704103200, "amount": "-12.50", "memo": "Coffee"}`` into
    entries between the bank and a suspense account (deposits debit the bank). ``ts`` is the transaction
    time in POSIX seconds; entries are dated with its UTC calendar date and stamped with that instant."""
    entries = []
    for n, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
            amount, ts = to_decimal(item["amount"]), float(item["ts"])
        except (ValueError, KeyError, TypeError, FormatError) as exc:
            raise FormatError(f"bank feed line {n}: {exc!r}") from None
        if amount == 0:
            log.warning("skipping zero-amount bank feed line %d", n)
            continue
        booked = from_timestamp(ts)
        postings = (Posting(bank_account, Money(amount, currency)), Posting(suspense_account, Money(-amount, currency)))
        entries.append(JournalEntry(booked.date(), item.get("memo", ""), postings,
                                    reference=str(item.get("id") or f"feed-{n}"), created_at=booked))
    return entries
