import importlib.metadata
import json
from datetime import date, datetime

import pytest

from ledgerkit.accounts import Account, AccountType, ChartOfAccounts
from ledgerkit.errors import FormatError
from ledgerkit.formats import dump_ledger, load_ledger
from ledgerkit.journal import JournalEntry, Ledger, Posting

STAMP = datetime(2024, 4, 1, 7, 45, 0)


def _ledger() -> Ledger:
    ledger = Ledger(ChartOfAccounts([
        Account("1000", "Cash", AccountType.ASSET),
        Account("1200", "Bank EUR", AccountType.ASSET, "EUR"),
        Account("4000", "Sales", AccountType.INCOME),
        Account("4100", "Export Sales", AccountType.INCOME, "EUR", parent="4000"),
    ]))
    ledger.post(JournalEntry(date(2024, 4, 1), "Shop", (Posting.debit("1000", "19.90"), Posting.credit("4000", "19.90")),
                             entry_id="e1", created_at=STAMP))
    ledger.post(JournalEntry(date(2024, 4, 3), "Export", (Posting.debit("1200", "250", "EUR", memo="wire"),
                                                         Posting.credit("4100", "250", "EUR")),
                             reference="EX-1", entry_id="e2", created_at=STAMP))
    ledger.locked_through = date(2024, 3, 31)
    return ledger


def _document(**overrides):
    document = {"formatVersion": "1.2.0", "accounts": [{"code": "1000", "name": "Bank", "type": "asset"},
                                                       {"code": "4000", "name": "Sales", "type": "income"}],
                "entries": [{"id": "x1", "date": "2024-05-01", "description": "Sale", "createdAt": "2024-05-01T10:00:00Z",
                             "postings": [{"accountCode": "1000", "amount": "5"}, {"accountCode": "4000", "amount": "-5"}]}]}
    document.update(overrides)
    return document


def _error(document) -> str:
    with pytest.raises(FormatError) as info:
        load_ledger(json.dumps(document))
    return str(info.value)


def test_marshmallow_is_pinned_to_4_0_1():
    assert importlib.metadata.version("marshmallow") == "4.0.1"


def test_dump_output_is_unchanged():
    document = json.loads(dump_ledger(_ledger(), currency="EUR", meta={"source": "erp", "batch": [1, {"n": 2}]}))
    assert document == {
        "formatVersion": "1.4.0", "currency": "EUR", "lockedThrough": "2024-03-31",
        "meta": {"source": "erp", "batch": [1, {"n": 2}]},
        "accounts": [
            {"code": "1000", "name": "Cash", "type": "asset", "currency": "USD", "parent": None},
            {"code": "1200", "name": "Bank EUR", "type": "asset", "currency": "EUR", "parent": None},
            {"code": "4000", "name": "Sales", "type": "income", "currency": "USD", "parent": None},
            {"code": "4100", "name": "Export Sales", "type": "income", "currency": "EUR", "parent": "4000"}],
        "entries": [
            {"id": "e1", "date": "2024-04-01", "description": "Shop", "reference": "", "createdAt": "2024-04-01T07:45:00Z",
             "postings": [{"accountCode": "1000", "amount": "19.90", "currency": "USD", "memo": ""},
                          {"accountCode": "4000", "amount": "-19.90", "currency": "USD", "memo": ""}]},
            {"id": "e2", "date": "2024-04-03", "description": "Export", "reference": "EX-1",
             "createdAt": "2024-04-01T07:45:00Z",
             "postings": [{"accountCode": "1200", "amount": "250", "currency": "EUR", "memo": "wire"},
                          {"accountCode": "4100", "amount": "-250", "currency": "EUR", "memo": ""}]}]}
    assert json.loads(dump_ledger(Ledger(ChartOfAccounts())))["meta"] == {}


def test_round_trip():
    text = dump_ledger(_ledger(), meta={"k": "v"})
    ledger, meta = load_ledger(text)
    assert meta == {"k": "v"}
    assert ledger.locked_through == date(2024, 3, 31)
    assert ledger.to_dict() == _ledger().to_dict()
    assert dump_ledger(ledger, meta=meta) == text


def test_document_currency_is_the_posting_default():
    eur = _document(currency="EUR", accounts=[{"code": "1000", "name": "Bank", "type": "asset", "currency": "EUR"},
                                               {"code": "4000", "name": "Sales", "type": "income", "currency": "EUR"}])
    ledger, _ = load_ledger(json.dumps(eur))
    assert {p.amount.currency for p in ledger.entries[0].postings} == {"EUR"}
    usd, _ = load_ledger(json.dumps(_document()))
    assert {p.amount.currency for p in usd.entries[0].postings} == {"USD"}
    mixed = _document(currency="JPY", accounts=[{"code": "1000", "name": "Bank", "type": "asset", "currency": "JPY"},
                                                {"code": "4000", "name": "Sales", "type": "income"}])
    mixed["entries"][0]["postings"] = [{"accountCode": "1000", "amount": "500"},
                                       {"accountCode": "4000", "amount": "-500", "currency": "JPY"}]
    with pytest.raises(FormatError):  # 4000 is a USD account, the JPY posting is rejected by the ledger
        load_ledger(json.dumps(mixed))
    again, _ = load_ledger(json.dumps(_document()))
    assert {p.amount.currency for p in again.entries[0].postings} == {"USD"}


def test_unknown_keys_and_missing_optional_fields():
    document = _document(generator="ledgerkit 0.8", lockedThrough=None)
    document["accounts"][0]["colour"] = "blue"
    document["entries"][0]["approvedBy"] = "jane"
    document["entries"][0]["postings"][0]["taxCode"] = "V20"
    ledger, meta = load_ledger(json.dumps(document))
    assert meta == {}
    assert ledger.locked_through is None
    entry = ledger.entries[0]
    assert (entry.entry_id, entry.reference, entry.created_at) == ("x1", "", datetime(2024, 5, 1, 10, 0))
    assert [p.memo for p in entry.postings] == ["", ""]
    no_entries = _document()
    del no_entries["entries"]
    assert load_ledger(json.dumps(no_entries))[0].entries == []


def test_errors_are_reported_with_field_paths():
    document = _document()
    document["entries"][0]["postings"][1]["currency"] = "ZZZ"
    assert "entries.0.postings.1.currency: unknown currency 'ZZZ'" in _error(document)
    assert _error(_document(formatVersion="1.9.0")).startswith("formatVersion: format version 1.9.0 is newer")
    assert _error(_document(formatVersion="2.0.0")).startswith("formatVersion: unsupported format version 2.0.0")
    assert _error(_document(formatVersion="latest")).startswith("formatVersion: invalid format version")
    missing = _document()
    del missing["formatVersion"]
    assert _error(missing).startswith("formatVersion: ")
    bad_type = _document()
    bad_type["accounts"][1]["type"] = "revenue"
    assert _error(bad_type).startswith("accounts.1.type: ")
    single = _document()
    single["entries"][0]["postings"] = single["entries"][0]["postings"][:1]
    assert _error(single).startswith("entries.0.postings: ")
    stamp = _document()
    stamp["entries"][0]["createdAt"] = "yesterday"
    assert "createdAt" in _error(stamp)
