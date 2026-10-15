import sqlite3
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from sensorpipe.buffer import ReadingBuffer
from sensorpipe.readings import Reading

UTC = timezone.utc
LEGACY_SCHEMA = """
CREATE TABLE readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id TEXT NOT NULL,
    channel TEXT NOT NULL,
    ts TIMESTAMP NOT NULL,
    value REAL NOT NULL,
    unit TEXT NOT NULL,
    quality TEXT NOT NULL DEFAULT 'good',
    sent INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX readings_ts ON readings (ts);
"""


def reading(ts, value=1.0, device="TT-101"):
    return Reading(device, "temp", ts, value, "degC")


def legacy_buffer(path):
    """A buffer file as written by the previous release (naive UTC text timestamps)."""
    conn = sqlite3.connect(path)
    conn.executescript(LEGACY_SCHEMA)
    conn.executemany(
        "INSERT INTO readings (device_id, channel, ts, value, unit, sent) VALUES (?, ?, ?, ?, ?, ?)",
        [("TT-101", "temp", "2024-03-01 10:00:00", 10.0, "degC", 1),
         ("TT-101", "temp", "2024-03-01 09:30:00.250000", 9.5, "degC", 0),
         ("PT-201", "pressure", "2024-03-01 11:15:00", 1.02, "bar", 0)],
    )
    conn.commit()
    conn.close()


def assert_utc(value, expected):
    assert value == expected and value.utcoffset() == timedelta(0)


def test_round_trip_preserves_instants(tmp_path):
    buffer = ReadingBuffer(tmp_path / "buffer.sqlite3")
    berlin = ZoneInfo("Europe/Berlin")
    readings = [reading(datetime(2024, 7, 1, 12, 0, 0, 123456, tzinfo=berlin), 3.0),
                reading(datetime(2024, 7, 1, 9, 0, tzinfo=UTC), 1.0),
                reading(datetime(2024, 7, 1, 9, 30, 0, 1, tzinfo=UTC), 2.0)]
    assert buffer.append(readings) == 3
    pending = buffer.pending()
    assert [r.value for _, r in pending] == [1.0, 2.0, 3.0]
    assert_utc(pending[1][1].timestamp, datetime(2024, 7, 1, 9, 30, 0, 1, tzinfo=UTC))
    assert_utc(pending[2][1].timestamp, datetime(2024, 7, 1, 10, 0, 0, 123456, tzinfo=UTC))
    assert_utc(buffer.oldest_pending(), datetime(2024, 7, 1, 9, 0, tzinfo=UTC))
    buffer.close()


def test_mark_sent_and_purge(tmp_path):
    buffer = ReadingBuffer()
    buffer.append([reading(datetime(2024, 7, 1, 9, m, tzinfo=UTC), float(m)) for m in (0, 10, 20, 30)])
    ids = [rid for rid, _ in buffer.pending(limit=3)]
    assert buffer.mark_sent(ids) == 3
    assert buffer.purge_before(datetime(2024, 7, 1, 11, 15, tzinfo=ZoneInfo("Europe/Berlin"))) == 2
    assert buffer.count() == 2 and buffer.count(pending_only=True) == 1
    assert buffer.purge_before(datetime(2024, 7, 1, 10, 0, tzinfo=UTC), sent_only=False) == 2
    assert buffer.oldest_pending() is None


def test_legacy_buffer_files_are_readable(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    legacy_buffer(path)
    buffer = ReadingBuffer(path)
    pending = buffer.pending()
    assert [(r.device_id, r.value) for _, r in pending] == [("TT-101", 9.5), ("PT-201", 1.02)]
    assert_utc(pending[0][1].timestamp, datetime(2024, 3, 1, 9, 30, 0, 250000, tzinfo=UTC))
    assert_utc(pending[1][1].timestamp, datetime(2024, 3, 1, 11, 15, tzinfo=UTC))
    assert_utc(buffer.oldest_pending(), datetime(2024, 3, 1, 9, 30, 0, 250000, tzinfo=UTC))
    assert [r.device_id for _, r in buffer.pending(device_id="PT-201")] == ["PT-201"]
    buffer.close()


def test_old_and_new_rows_mix(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    legacy_buffer(path)
    buffer = ReadingBuffer(path)
    buffer.append([reading(datetime(2024, 3, 1, 9, 45, tzinfo=UTC), 9.75),
                   reading(datetime(2024, 3, 1, 8, 0, tzinfo=UTC), 8.0)])
    assert [r.value for _, r in buffer.pending()] == [8.0, 9.5, 9.75, 1.02]
    assert_utc(buffer.oldest_pending(), datetime(2024, 3, 1, 8, 0, tzinfo=UTC))
    early = [rid for rid, r in buffer.pending() if r.value == 8.0]
    buffer.mark_sent(early)
    # removes the new 08:00 row only; the legacy 10:00 row (already sent) is newer than the cutoff
    assert buffer.purge_before(datetime(2024, 3, 1, 9, 0, tzinfo=UTC)) == 1
    assert buffer.count() == 4
    assert buffer.purge_before(datetime(2024, 3, 1, 10, 0, 0, 1, tzinfo=UTC)) == 1
    assert buffer.count() == 3
    buffer.close()
    reopened = ReadingBuffer(path)
    assert [r.value for _, r in reopened.pending(limit=2)] == [9.5, 9.75]
    reopened.close()


@pytest.mark.parametrize("ts", [datetime(2024, 12, 31, 23, 59, 59, 999999, tzinfo=UTC),
                                datetime(2000, 1, 1, tzinfo=ZoneInfo("Asia/Tokyo"))])
def test_edge_timestamps(ts):
    buffer = ReadingBuffer()
    buffer.append([reading(ts)])
    (_, stored), = buffer.pending()
    assert_utc(stored.timestamp, ts.astimezone(UTC))
    buffer.close()
