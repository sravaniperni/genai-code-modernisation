import json
import logging
import os
import re
from datetime import date
from decimal import Decimal
from pathlib import Path

from ledgerkit.importers import read_bank_feed, read_csv
from ledgerkit.money import Money
from ledgerkit.rates import RateTable

CSV = """date,reference,description,account,debit,credit,currency
2024-02-01,INV-7,Consulting,1100,"1,250.00",,USD
2024-02-01,INV-7,Consulting,4000,,"1,250.00",USD
,,,,,,
2024-02-03,EXP-1,Rent,6100,800,,
2024-02-03,EXP-1,Rent memo only,,,,
2024-02-03,EXP-1,Rent,1000,,800,
"""


def _warnings(caplog):
    return [(r.levelname, r.getMessage()) for r in caplog.records if r.levelno >= logging.WARNING]


def test_csv_skips_are_logged_as_warnings(caplog):
    caplog.set_level(logging.WARNING)
    entries = read_csv(CSV)
    assert [(e.reference, len(e.postings)) for e in entries] == [("INV-7", 2), ("EXP-1", 2)]
    assert [p.amount.amount for p in entries[1].postings] == [Decimal("800"), Decimal("-800")]
    assert _warnings(caplog) == [("WARNING", "skipping blank CSV row 4"),
                                 ("WARNING", "skipping CSV row 6: no account given")]


def test_bank_feed_skips_are_logged_as_warnings(caplog):
    caplog.set_level(logging.WARNING)
    lines = [json.dumps({"id": "a", "ts": 1706781600, "amount": "10.00", "memo": "in"}),
             json.dumps({"id": "b", "ts": 1706781700, "amount": "0.00", "memo": "noise"}),
             json.dumps({"id": "c", "ts": 1706781800, "amount": "-4.50", "memo": "out"})]
    entries = read_bank_feed(lines, bank_account="1000", suspense_account="2000")
    assert [e.reference for e in entries] == ["a", "c"]
    assert _warnings(caplog) == [("WARNING", "skipping zero-amount bank feed line 2")]


def test_stale_rates_are_logged_as_warnings(caplog):
    caplog.set_level(logging.WARNING)
    table = RateTable(max_age_days=7)
    table.add("EUR", "USD", "1.10", date(2024, 1, 1))
    assert table.rate("EUR", "USD", date(2024, 1, 8)) == Decimal("1.10")
    assert _warnings(caplog) == []
    assert table.convert(Money("100.00", "EUR"), "USD", date(2024, 2, 1)) == Money("110.00", "USD")
    assert table.rate("USD", "EUR", date(2024, 3, 1)) == Decimal(1) / Decimal("1.10")
    assert _warnings(caplog) == [("WARNING", "using stale EUR/USD rate from 2024-01-01 for 2024-02-01"),
                                 ("WARNING", "using stale EUR/USD rate from 2024-01-01 for 2024-03-01")]


def test_no_deprecated_warn_calls_left():
    source = Path(os.environ["REPO_ROOT"], "src", "ledgerkit")
    pattern = re.compile(r"\b(log|logger|logging|_log|LOG|LOGGER)\.warn\(")
    assert [str(p) for p in source.rglob("*.py") if pattern.search(p.read_text(encoding="utf-8"))] == []
