import json
from datetime import date

import pytest

from ledgerkit.errors import FormatError
from ledgerkit.formats import dump_ledger, load_ledger


def test_dump_and_load_round_trip(ledger):
    ledger.locked_through = date(2024, 1, 5)
    text = dump_ledger(ledger, meta={"source": "tests"})
    document = json.loads(text)
    assert document["formatVersion"] == "1.4.0"
    assert document["entries"][0]["postings"][0] == {"accountCode": "1000", "amount": "10000", "currency": "USD", "memo": ""}
    loaded, meta = load_ledger(text)
    assert meta == {"source": "tests"}
    assert loaded.locked_through == date(2024, 1, 5)
    assert loaded.to_dict() == ledger.to_dict()


def test_load_defaults_and_unknown_keys():
    document = {"formatVersion": "1.1.0", "currency": "EUR", "generator": "ledgerkit 0.7",
                "accounts": [{"code": "1000", "name": "Bank", "type": "asset", "currency": "EUR", "color": "red"},
                             {"code": "4000", "name": "Sales", "type": "income", "currency": "EUR"}],
                "entries": [{"id": "e1", "date": "2024-03-01", "description": "Sale", "createdAt": "2024-03-01T08:00:00Z",
                             "postings": [{"accountCode": "1000", "amount": "10.00"},
                                          {"accountCode": "4000", "amount": "-10.00", "memo": "web shop"}]}]}
    ledger, meta = load_ledger(json.dumps(document))
    assert meta == {}
    assert ledger.balance("4000").amount == 10
    assert ledger.entries[0].postings[1].memo == "web shop"
    assert ledger.entries[0].postings[0].amount.currency == "EUR"


def test_load_rejects_bad_documents():
    for change in ({"formatVersion": "2.0.0"}, {"formatVersion": "1.9.0"}, {"formatVersion": "one"}, {"accounts": "x"}):
        with pytest.raises(FormatError):
            load_ledger(json.dumps({"formatVersion": "1.0.0", "accounts": [], "entries": [], **change}))
    with pytest.raises(FormatError):
        load_ledger("[1, 2]")


def test_load_reports_field_errors():
    document = {"formatVersion": "1.0.0", "accounts": [{"code": "1000", "name": "Cash", "type": "asset"}],
                "entries": [{"id": "e", "date": "2024-01-01", "description": "x", "createdAt": "2024-01-01T00:00:00Z",
                             "postings": [{"accountCode": "1000", "amount": "1", "currency": "ZZZ"},
                                          {"accountCode": "1000", "amount": "-1"}]}]}
    with pytest.raises(FormatError, match="unknown currency 'ZZZ'"):
        load_ledger(json.dumps(document))
