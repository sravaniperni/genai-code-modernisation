"""Local SQLite store-and-forward buffer: gateways queue readings while the uplink is down."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

from sensorpipe.readings import Reading
from sensorpipe.timeutil import UTC

_SCHEMA = """
CREATE TABLE IF NOT EXISTS readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id TEXT NOT NULL,
    channel TEXT NOT NULL,
    ts TIMESTAMP NOT NULL,
    value REAL NOT NULL,
    unit TEXT NOT NULL,
    quality TEXT NOT NULL DEFAULT 'good',
    sent INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS readings_ts ON readings (ts);
"""
_COLUMNS = "id, device_id, channel, ts, value, unit, quality"


def _naive_utc(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(tzinfo=None)


class ReadingBuffer:
    def __init__(self, path: str | Path = ":memory:"):
        self.path = str(path)
        self._conn = sqlite3.connect(self.path, detect_types=sqlite3.PARSE_DECLTYPES)
        self._conn.executescript(_SCHEMA)

    def close(self) -> None:
        self._conn.close()

    @staticmethod
    def _reading(row: tuple) -> tuple[int, Reading]:
        rid, device_id, channel, ts, value, unit, quality = row
        return rid, Reading(device_id, channel, ts.replace(tzinfo=UTC), value, unit, quality)

    def append(self, readings: Iterable[Reading]) -> int:
        rows = [(r.device_id, r.channel, _naive_utc(r.timestamp), r.value, r.unit, r.quality) for r in readings]
        with self._conn:
            self._conn.executemany(
                "INSERT INTO readings (device_id, channel, ts, value, unit, quality) VALUES (?, ?, ?, ?, ?, ?)", rows
            )
        return len(rows)

    def pending(self, limit: int | None = None, device_id: str | None = None) -> list[tuple[int, Reading]]:
        """Unsent readings as ``(row id, reading)`` pairs, oldest first."""
        sql = f"SELECT {_COLUMNS} FROM readings WHERE sent = 0"
        params: list[object] = []
        if device_id is not None:
            sql += " AND device_id = ?"
            params.append(device_id)
        sql += " ORDER BY ts, id"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        return [self._reading(row) for row in self._conn.execute(sql, params)]

    def oldest_pending(self) -> datetime | None:
        row = self._conn.execute("SELECT ts FROM readings WHERE sent = 0 ORDER BY ts, id LIMIT 1").fetchone()
        return row[0].replace(tzinfo=UTC) if row else None

    def mark_sent(self, ids: Iterable[int]) -> int:
        with self._conn:
            cur = self._conn.executemany("UPDATE readings SET sent = 1 WHERE id = ?", [(int(i),) for i in ids])
        return cur.rowcount

    def purge_before(self, cutoff: datetime, sent_only: bool = True) -> int:
        """Delete readings older than ``cutoff`` (only already forwarded ones unless ``sent_only`` is false)."""
        sql = "DELETE FROM readings WHERE ts < ?" + (" AND sent = 1" if sent_only else "")
        with self._conn:
            cur = self._conn.execute(sql, (_naive_utc(cutoff),))
        return cur.rowcount

    def count(self, pending_only: bool = False) -> int:
        sql = "SELECT COUNT(*) FROM readings" + (" WHERE sent = 0" if pending_only else "")
        return int(self._conn.execute(sql).fetchone()[0])
