from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from sensorpipe.errors import IngestError
from sensorpipe.readings import Reading, ReadingBatch, parse_timestamp

UTC = timezone.utc


def test_parse_iso_timestamps():
    assert parse_timestamp("2024-01-15T09:00:00+01:00") == datetime(2024, 1, 15, 8, tzinfo=UTC)
    ts = parse_timestamp("2024-01-15 09:00:00", tz="Europe/Berlin")
    assert ts == datetime(2024, 1, 15, 8, tzinfo=UTC)
    assert ts.utcoffset() == timedelta(0)


def test_parse_epoch_seconds_and_milliseconds():
    assert parse_timestamp(1705305600) == datetime(2024, 1, 15, 8, tzinfo=UTC)
    assert parse_timestamp(1705305600500) == datetime(2024, 1, 15, 8, 0, 0, 500000, tzinfo=UTC)


def test_parse_custom_format_and_garbage():
    ts = parse_timestamp("15.01.2024 09:30:00", tz="Europe/Berlin", fmt="DD.MM.YYYY HH:mm:ss")
    assert ts == datetime(2024, 1, 15, 8, 30, tzinfo=UTC)
    with pytest.raises(IngestError):
        parse_timestamp("yesterday-ish")
    with pytest.raises(IngestError):
        parse_timestamp("   ")


def test_reading_requires_aware_timestamp():
    with pytest.raises(ValueError):
        Reading("d", "c", datetime(2024, 1, 1), 1.0, "V")


def test_batch_is_sorted_and_exposes_arrays(make_readings):
    readings = make_readings([1.0, 2.0, 3.0])
    batch = ReadingBatch(reversed(readings))
    assert [r.value for r in batch] == [1.0, 2.0, 3.0]
    assert batch.values().dtype == np.float64
    assert np.diff(batch.epochs()).tolist() == [60.0, 60.0]
    assert batch.unit == "degC" and len(batch[1:]) == 2
