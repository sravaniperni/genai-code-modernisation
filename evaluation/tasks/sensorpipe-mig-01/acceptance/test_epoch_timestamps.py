import io
import json
import math
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest

from sensorpipe.ingest import read_csv, read_json
from sensorpipe.readings import ReadingBatch, from_epoch, parse_timestamp

UTC = timezone.utc


def assert_utc(value, expected):
    assert value == expected
    assert value.tzinfo is not None and value.utcoffset() == timedelta(0)


@pytest.mark.parametrize("raw, expected", [
    (1700000000, datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC)),
    (1700000000.25, datetime(2023, 11, 14, 22, 13, 20, 250000, tzinfo=UTC)),
    (1700000000123, datetime(2023, 11, 14, 22, 13, 20, 123000, tzinfo=UTC)),
    (0, datetime(1970, 1, 1, tzinfo=UTC)),
    (-86400, datetime(1969, 12, 31, tzinfo=UTC)),
])
def test_from_epoch(raw, expected):
    assert_utc(from_epoch(raw), expected)


def test_parse_timestamp_numbers_and_numeric_strings():
    assert_utc(parse_timestamp(1705305600), datetime(2024, 1, 15, 8, tzinfo=UTC))
    assert_utc(parse_timestamp("1705305600"), datetime(2024, 1, 15, 8, tzinfo=UTC))
    assert_utc(parse_timestamp("1705305600500"), datetime(2024, 1, 15, 8, 0, 0, 500000, tzinfo=UTC))
    assert_utc(parse_timestamp(" 1705305600.75 ", tz="Europe/Berlin"), datetime(2024, 1, 15, 8, 0, 0, 750000, tzinfo=UTC))


def test_ingest_epoch_values():
    doc = {"device_id": "FT-7", "channel": "flow", "unit": "m3/h",
           "readings": [{"ts": 1705305660000, "value": 2.0}, {"ts": 1705305600, "value": 1.0}]}
    readings = read_json(io.StringIO(json.dumps(doc)))
    assert_utc(readings[0].timestamp, datetime(2024, 1, 15, 8, 1, tzinfo=UTC))
    assert_utc(readings[1].timestamp, datetime(2024, 1, 15, 8, 0, tzinfo=UTC))
    csv_readings = read_csv(io.StringIO("timestamp,value\n1705305600,1.5\n1705305600250,2.5\n"),
                            device_id="FT-7", channel="flow", unit="m3/h", tz="America/New_York")
    assert_utc(csv_readings[1].timestamp, datetime(2024, 1, 15, 8, 0, 0, 250000, tzinfo=UTC))


def test_batch_from_epoch_arrays():
    epochs = np.array([1705305600.0, 1705305660.0, 1705305720.5])
    batch = ReadingBatch.from_arrays(epochs, np.array([1.0, np.nan, 3.0]), device_id="FT-7", channel="flow",
                                     unit="m3/h")
    assert [r.quality for r in batch] == ["good", "gap", "good"]
    assert_utc(batch[0].timestamp, datetime(2024, 1, 15, 8, 0, tzinfo=UTC))
    assert_utc(batch[2].timestamp, datetime(2024, 1, 15, 8, 2, 0, 500000, tzinfo=UTC))
    assert math.isnan(batch[1].value) and batch[2].value == 3.0
    assert batch.epochs().tolist() == epochs.tolist()


def test_no_utcfromtimestamp_left_in_sources():
    src = Path(os.environ.get("REPO_ROOT", ".")) / "src"
    offenders = [str(p) for p in src.rglob("*.py") if re.search(r"\butcfromtimestamp\s*\(", p.read_text())]
    assert offenders == []
