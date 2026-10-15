from datetime import date
from decimal import Decimal

import pytest

from ledgerkit.errors import FormatError
from ledgerkit.schemas import entry_payload, parse_entry

PAYLOAD = {"date": "2024-05-02", "description": "Office rent", "reference": "R-5",
           "postings": [{"account": "6100", "debit": "1500.00"}, {"account": "1000", "credit": "1500.00"}]}


def test_parse_entry_builds_journal_entry():
    entry = parse_entry(PAYLOAD)
    assert entry.date == date(2024, 5, 2)
    assert entry.reference == "R-5"
    assert [p.amount.amount for p in entry.postings] == [Decimal("1500.00"), Decimal("-1500.00")]
    entry.validate()


def test_parse_entry_rejects_invalid_payloads():
    cases = [
        ({"postings": [{"account": "6100", "debit": "10"}, {"account": "1000", "credit": "9"}]}, "does not balance"),
        ({"postings": [{"account": "6100", "debit": "10", "credit": "10"}, {"account": "1000", "credit": "0"}]},
         "exactly one of debit or credit"),
        ({"postings": [{"account": "6100", "debit": "10", "currency": "XYZ"}, {"account": "1000", "credit": "10"}]},
         "unsupported currency"),
        ({"description": ""}, "description"),
        ({"unexpected": True}, "unexpected"),
    ]
    for change, fragment in cases:
        with pytest.raises(FormatError) as info:
            parse_entry({**PAYLOAD, **change})
        assert fragment in str(info.value)


def test_entry_payload_round_trip():
    payload = entry_payload(parse_entry(PAYLOAD))
    assert payload["date"] == "2024-05-02"
    assert payload["postings"][0] == {"account": "6100", "debit": "1500.00", "credit": "0", "currency": "USD", "memo": ""}
    assert parse_entry(payload).postings == parse_entry(PAYLOAD).postings
