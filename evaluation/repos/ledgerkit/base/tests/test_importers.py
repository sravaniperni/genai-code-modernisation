import json
from datetime import date
from decimal import Decimal

import pytest

from ledgerkit.errors import FormatError
from ledgerkit.importers import read_bank_feed, read_csv

CSV = """date,reference,description,account,debit,credit,currency
2024-02-01,INV-7,Consulting,1100,"1,250.00",,USD
2024-02-01,INV-7,Consulting,4000,,"1,250.00",USD
,,,,,,
2024-02-03,EXP-1,Rent,6100,800,,
2024-02-03,EXP-1,Rent,1000,,800,
"""


def test_read_csv_groups_rows_by_reference(caplog):
    entries = read_csv(CSV)
    assert [e.reference for e in entries] == ["INV-7", "EXP-1"]
    assert entries[0].date == date(2024, 2, 1)
    assert [p.amount.amount for p in entries[0].postings] == [Decimal("1250.00"), Decimal("-1250.00")]
    assert entries[1].postings[0].amount.currency == "USD"
    assert "skipping blank CSV row 4" in caplog.text


def test_read_csv_reports_line_numbers():
    with pytest.raises(FormatError, match="line 2"):
        read_csv("date,reference,description,account,debit,credit\n2024-13-01,R,x,1000,5,\n")


def test_bank_feed_creates_balanced_entries():
    lines = [json.dumps({"id": "tx-1", "ts": 1706781600, "amount": "250.00", "memo": "Customer payment"}),
             "",
             json.dumps({"id": "tx-2", "ts": 1706868000, "amount": "-12.50", "memo": "Coffee"})]
    entries = read_bank_feed(lines, bank_account="1000", suspense_account="2000")
    assert [e.date for e in entries] == [date(2024, 2, 1), date(2024, 2, 2)]
    assert [p.amount.amount for p in entries[1].postings] == [Decimal("-12.50"), Decimal("12.50")]
    assert entries[0].reference == "tx-1"
    with pytest.raises(FormatError):
        read_bank_feed(['{"id": "x", "amount": "1"}'], bank_account="1000", suspense_account="2000")
