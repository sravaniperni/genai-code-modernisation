import sqlite3
from datetime import date, datetime

import pytest

from ledgerkit.accounts import Account, AccountType, ChartOfAccounts
from ledgerkit.audit import AuditLog
from ledgerkit.journal import JournalEntry, Ledger, Posting

LEGACY_SCHEMA = """CREATE TABLE audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, at TIMESTAMP NOT NULL, day DATE NOT NULL,
    action TEXT NOT NULL, entry_id TEXT, detail TEXT NOT NULL DEFAULT '')"""


def test_events_round_trip_with_types():
    log = AuditLog()
    log.record("import", day=date(2024, 1, 3), detail="bank feed", at=datetime(2024, 1, 4, 9, 30, 15, 250))
    log.record("post", day=date(2024, 1, 5), entry_id="e1", at=datetime(2024, 1, 5, 8, 0))
    events = log.events()
    assert [(e.action, e.at, e.day, e.entry_id, e.detail) for e in events] == [
        ("import", datetime(2024, 1, 4, 9, 30, 15, 250), date(2024, 1, 3), None, "bank feed"),
        ("post", datetime(2024, 1, 5, 8, 0), date(2024, 1, 5), "e1", ""),
    ]
    assert all(type(e.at) is datetime and type(e.day) is date for e in events)


def test_events_are_chronological_and_filtered():
    log = AuditLog()
    log.record("post", day=date(2024, 2, 10), entry_id="b", at=datetime(2024, 2, 11, 12, 0))
    log.record("post", day=date(2024, 2, 1), entry_id="a", at=datetime(2024, 2, 1, 9, 0, 0, 1))
    log.record("close", day=date(2024, 2, 29), at=datetime(2024, 3, 2, 18, 30))
    log.record("post", day=date(2024, 3, 1), entry_id="c", at=datetime(2024, 3, 2, 8, 15))
    assert [e.entry_id or e.action for e in log.events()] == ["a", "b", "c", "close"]
    assert [e.entry_id for e in log.events(start=date(2024, 2, 10), end=date(2024, 3, 1), action="post")] == ["b", "c"]
    assert [e.action for e in log.events(start=date(2024, 2, 29), end=date(2024, 2, 29))] == ["close"]
    assert log.events(end=date(2024, 1, 31)) == []
    assert [e.entry_id for e in log.events(action="post", start=date(2024, 2, 2))] == ["b", "c"]


def test_last_activity():
    log = AuditLog()
    assert log.last_activity() is None
    log.record("post", day=date(2024, 1, 1), at=datetime(2024, 1, 2, 10, 0, 0, 999999))
    log.record("post", day=date(2024, 1, 1), at=datetime(2024, 1, 2, 9, 0))
    last = log.last_activity()
    assert type(last) is datetime and last == datetime(2024, 1, 2, 10, 0, 0, 999999)


def test_databases_from_earlier_releases(tmp_path):
    path = tmp_path / "audit.db"
    with sqlite3.connect(path) as conn:
        conn.execute(LEGACY_SCHEMA)
        conn.executemany("INSERT INTO audit_events (at, day, action, entry_id, detail) VALUES (?, ?, ?, ?, ?)", [
            ("2024-01-05 09:00:00", "2024-01-05", "post", "old-1", "legacy"),
            ("2024-01-04 17:45:10.250000", "2024-01-04", "import", None, "csv"),
        ])
    conn.close()
    log = AuditLog(str(path))
    events = log.events()
    assert [(e.at, e.day, e.entry_id) for e in events] == [
        (datetime(2024, 1, 4, 17, 45, 10, 250000), date(2024, 1, 4), None),
        (datetime(2024, 1, 5, 9, 0), date(2024, 1, 5), "old-1"),
    ]
    log.record("post", day=date(2024, 1, 5), entry_id="new-1", at=datetime(2024, 1, 5, 8, 0))
    log.record("post", day=date(2024, 1, 5), entry_id="new-2", at=datetime(2024, 1, 5, 9, 30))
    assert [e.entry_id for e in AuditLog(str(path)).events(start=date(2024, 1, 5))] == ["new-1", "old-1", "new-2"]
    assert AuditLog(str(path)).last_activity() == datetime(2024, 1, 5, 9, 30)


def test_ledger_postings_are_audited():
    chart = ChartOfAccounts([Account("1000", "Cash", AccountType.ASSET), Account("6100", "Rent", AccountType.EXPENSE)])
    log = AuditLog(clock=lambda: datetime(2024, 2, 1, 12, 0, 30))
    ledger = Ledger(chart, audit=log)
    entry = ledger.post(JournalEntry(date(2024, 1, 31), "Rent", (Posting.debit("6100", "5"), Posting.credit("1000", "5")),
                                     created_at=datetime(2024, 2, 1, 12, 0, 30)))
    (event,) = log.events(start=date(2024, 1, 31), end=date(2024, 1, 31))
    assert (event.action, event.entry_id, event.at, event.day, event.detail) == (
        "post", entry.entry_id, datetime(2024, 2, 1, 12, 0, 30), date(2024, 1, 31), "Rent")
