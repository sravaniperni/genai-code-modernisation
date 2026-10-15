import json
import os
import re
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from ledgerkit.accounts import Account, AccountType, ChartOfAccounts
from ledgerkit.importers import read_bank_feed
from ledgerkit.journal import JournalEntry, Ledger, Posting, format_timestamp, from_timestamp, parse_timestamp

UTC = timezone.utc


@pytest.fixture
def far_from_utc(monkeypatch):
    """Run with the process-local time zone at UTC+14 so local/UTC mix-ups change calendar dates."""
    monkeypatch.setenv("TZ", "LINT-14")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


def _entry(**kwargs) -> JournalEntry:
    return JournalEntry(date(2024, 1, 31), "Rent", (Posting.debit("6100", "800"), Posting.credit("1000", "800")), **kwargs)


def _assert_utc(value: datetime) -> None:
    assert value.tzinfo is not None and value.utcoffset() == timedelta(0)


def test_new_entries_are_stamped_with_aware_utc(far_from_utc):
    before = datetime.now(UTC)
    entry = _entry()
    after = datetime.now(UTC)
    _assert_utc(entry.created_at)
    assert before - timedelta(seconds=1) <= entry.created_at <= after + timedelta(seconds=1)


def test_serialised_form_is_unchanged():
    entry = _entry(created_at=datetime(2024, 1, 31, 10, 0, 5, 123456, tzinfo=UTC))
    assert entry.to_dict()["created_at"] == "2024-01-31T10:00:05Z"
    assert format_timestamp(datetime(2023, 12, 31, 23, 59, 59, tzinfo=UTC)) == "2023-12-31T23:59:59Z"
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", _entry().to_dict()["created_at"])


def test_parsed_timestamps_are_aware_utc():
    parsed = parse_timestamp("2024-01-31T10:00:05Z")
    _assert_utc(parsed)
    assert parsed == datetime(2024, 1, 31, 10, 0, 5, tzinfo=UTC)
    restored = JournalEntry.from_dict(_entry(created_at=datetime(2024, 2, 1, 8, 30, tzinfo=UTC)).to_dict())
    _assert_utc(restored.created_at)
    assert restored.created_at == datetime(2024, 2, 1, 8, 30, tzinfo=UTC)


def test_ledger_round_trip_keeps_aware_timestamps():
    chart = ChartOfAccounts([Account("1000", "Cash", AccountType.ASSET), Account("6100", "Rent", AccountType.EXPENSE)])
    ledger = Ledger(chart)
    fresh = ledger.post(_entry())
    copy = Ledger.from_dict(json.loads(json.dumps(ledger.to_dict())))
    (restored,) = copy.entries
    _assert_utc(restored.created_at)
    assert restored.created_at == fresh.created_at.replace(microsecond=0)
    assert restored.created_at <= datetime.now(UTC)


def test_from_timestamp_is_aware_utc(far_from_utc):
    assert from_timestamp(0) == datetime(1970, 1, 1, tzinfo=UTC)
    value = from_timestamp(1704067199.5)
    _assert_utc(value)
    assert value == datetime(2023, 12, 31, 23, 59, 59, 500000, tzinfo=UTC)


def test_bank_feed_uses_utc_dates_and_instants(far_from_utc):
    lines = [json.dumps({"id": "late", "ts": 1704067199, "amount": "-20.00", "memo": "New year's eve"}),
             json.dumps({"id": "noon", "ts": 1704110400, "amount": "35.10", "memo": "Refund"})]
    late, noon = read_bank_feed(lines, bank_account="1000", suspense_account="2000")
    assert late.date == date(2023, 12, 31)
    assert late.created_at == datetime(2023, 12, 31, 23, 59, 59, tzinfo=UTC)
    _assert_utc(late.created_at)
    assert noon.date == date(2024, 1, 1)
    assert noon.to_dict()["created_at"] == "2024-01-01T12:00:00Z"


def test_deprecated_utc_constructors_are_gone():
    source = Path(os.environ["REPO_ROOT"], "src", "ledgerkit")
    offenders = [str(path) for path in source.rglob("*.py")
                 if re.search(r"\.utcnow\(|\.utcfromtimestamp\(", path.read_text(encoding="utf-8"))]
    assert offenders == []
