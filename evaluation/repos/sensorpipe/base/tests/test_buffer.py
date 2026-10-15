from datetime import datetime, timedelta, timezone

from sensorpipe.buffer import ReadingBuffer

UTC = timezone.utc


def test_append_and_pending_in_time_order(make_readings):
    buffer = ReadingBuffer()
    readings = make_readings([1.0, 2.0, 3.0])
    assert buffer.append(reversed(readings)) == 3
    pending = buffer.pending()
    assert [r.value for _, r in pending] == [1.0, 2.0, 3.0]
    assert pending[0][1].timestamp == readings[0].timestamp
    assert buffer.oldest_pending() == readings[0].timestamp
    assert len(buffer.pending(limit=2)) == 2


def test_mark_sent_and_purge(make_readings):
    buffer = ReadingBuffer()
    buffer.append(make_readings([1.0, 2.0, 3.0]))
    ids = [rid for rid, _ in buffer.pending(limit=2)]
    assert buffer.mark_sent(ids) == 2
    assert buffer.count(pending_only=True) == 1
    cutoff = datetime(2024, 1, 15, 9, 0, tzinfo=UTC)
    assert buffer.purge_before(cutoff) == 2
    assert buffer.count() == 1


def test_buffer_persists_to_file(tmp_path, make_readings):
    path = tmp_path / "buffer.sqlite3"
    buffer = ReadingBuffer(path)
    buffer.append(make_readings([5.0], start=datetime(2024, 1, 15, 9, 0, 0, 123456, tzinfo=UTC)))
    buffer.close()
    reopened = ReadingBuffer(path)
    (_, reading), = reopened.pending()
    assert reading.timestamp == datetime(2024, 1, 15, 9, 0, 0, 123456, tzinfo=UTC)
    assert reading.timestamp.utcoffset() == timedelta(0)
    reopened.close()
