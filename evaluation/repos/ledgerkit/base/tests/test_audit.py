from datetime import date, datetime

from ledgerkit.audit import AuditLog
from ledgerkit.journal import Ledger, Posting
from conftest import entry


def test_audit_log_records_and_filters():
    log = AuditLog()
    log.record("import", day=date(2024, 1, 3), detail="bank feed", at=datetime(2024, 1, 4, 9, 30, 15, 250))
    log.record("post", day=date(2024, 1, 5), entry_id="e1", at=datetime(2024, 1, 5, 8, 0))
    events = log.events()
    assert [(e.action, e.at, e.day) for e in events] == [
        ("import", datetime(2024, 1, 4, 9, 30, 15, 250), date(2024, 1, 3)),
        ("post", datetime(2024, 1, 5, 8, 0), date(2024, 1, 5)),
    ]
    assert [e.entry_id for e in log.events(start=date(2024, 1, 4))] == ["e1"]
    assert log.last_activity() == datetime(2024, 1, 5, 8, 0)


def test_ledger_reports_postings_to_audit_log(chart):
    log = AuditLog(clock=lambda: datetime(2024, 2, 1, 12, 0))
    ledger = Ledger(chart, audit=log)
    posted = ledger.post(entry(date(2024, 1, 31), "Rent", Posting.debit("6100", "5"), Posting.credit("1000", "5")))
    (event,) = log.events(action="post")
    assert (event.entry_id, event.at, event.detail) == (posted.entry_id, datetime(2024, 2, 1, 12, 0), "Rent")
