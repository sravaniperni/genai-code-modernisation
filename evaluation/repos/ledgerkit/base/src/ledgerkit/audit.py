"""Append-only audit trail kept in SQLite through the standard-library ``sqlite3`` module."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from typing import Callable

SCHEMA = """CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, at TIMESTAMP NOT NULL, day DATE NOT NULL,
    action TEXT NOT NULL, entry_id TEXT, detail TEXT NOT NULL DEFAULT '')"""


@dataclass(frozen=True)
class AuditEvent:
    id: int
    at: datetime
    day: date
    action: str
    entry_id: str | None
    detail: str


class AuditLog:
    """Ledger activity log (usable as the ``audit`` sink of :class:`ledgerkit.journal.Ledger`). ``at`` is the
    naive local time of the action and ``day`` the accounting date; both come back as datetime/date objects."""

    def __init__(self, path: str = ":memory:", *, clock: Callable[[], datetime] = datetime.now):
        self.clock = clock
        self._conn = sqlite3.connect(path, detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES)
        self._conn.execute(SCHEMA)

    def record(self, action: str, *, day: date, entry_id: str | None = None, detail: str = "",
               at: datetime | None = None) -> int:
        with self._conn:
            cursor = self._conn.execute("INSERT INTO audit_events (at, day, action, entry_id, detail) VALUES (?, ?, ?, ?, ?)",
                                        (at or self.clock(), day, action, entry_id, detail))
        return int(cursor.lastrowid or 0)

    def events(self, *, start: date | None = None, end: date | None = None, action: str | None = None) -> list[AuditEvent]:
        """Events whose ``day`` lies within ``start``..``end`` (inclusive), in the order they happened."""
        sql, params = "SELECT id, at, day, action, entry_id, detail FROM audit_events WHERE 1 = 1", []
        for clause, value in (("day >= ?", start), ("day <= ?", end), ("action = ?", action)):
            if value is not None:
                sql += f" AND {clause}"
                params.append(value)
        return [AuditEvent(*row) for row in self._conn.execute(sql + " ORDER BY at, id", params)]

    def last_activity(self) -> datetime | None:
        return self._conn.execute('SELECT MAX(at) AS "last [timestamp]" FROM audit_events').fetchone()[0]
