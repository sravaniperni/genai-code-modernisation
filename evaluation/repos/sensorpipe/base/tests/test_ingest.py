import io
import json
import math
from datetime import datetime, timezone

import pytest

from sensorpipe.errors import IngestError
from sensorpipe.ingest import group_batches, load_file, read_csv, read_json

UTC = timezone.utc

CSV = """timestamp,device_id,channel,value,unit
2024-01-15T08:00:00Z,TT-101,temp,21.5,degC
2024-01-15T08:01:00Z,TT-101,temp,,degC
2024-01-15T08:00:00Z,PT-201,pressure,1.02,bar
"""


def test_read_csv_with_all_columns():
    readings = read_csv(io.StringIO(CSV))
    assert len(readings) == 3
    first = readings[0]
    assert (first.device_id, first.channel, first.value, first.unit) == ("TT-101", "temp", 21.5, "degC")
    assert first.timestamp == datetime(2024, 1, 15, 8, tzinfo=UTC)
    assert math.isnan(readings[1].value) and readings[1].quality == "missing"


def test_read_csv_defaults_and_semicolons():
    text = "timestamp;value\n15.01.2024 09:00:00;4.2\n"
    readings = read_csv(io.StringIO(text), device_id="FT-7", channel="flow", unit="m3/h", tz="Europe/Berlin",
                        timestamp_format="DD.MM.YYYY HH:mm:ss", delimiter=";")
    assert readings[0].timestamp == datetime(2024, 1, 15, 8, tzinfo=UTC)
    assert readings[0].device_id == "FT-7"


def test_read_csv_errors_name_the_line():
    with pytest.raises(IngestError, match="line 3"):
        read_csv(io.StringIO("timestamp,value\n2024-01-15T08:00:00Z,1\n2024-01-15T08:01:00Z,abc\n"),
                 device_id="d", channel="c", unit="V")
    with pytest.raises(IngestError, match="value"):
        read_csv(io.StringIO("timestamp,reading\n"))


def test_read_json_document_and_list(tmp_path):
    doc = {"device_id": "TT-101", "channel": "temp", "unit": "degC",
           "readings": [{"ts": "2024-01-15T08:00:00Z", "value": 20.0}, {"ts": "2024-01-15T08:01:00Z", "value": None}]}
    readings = read_json(io.StringIO(json.dumps(doc)))
    assert [r.device_id for r in readings] == ["TT-101", "TT-101"]
    assert math.isnan(readings[1].value)
    path = tmp_path / "list.json"
    path.write_text(json.dumps([{"device_id": "A", "channel": "v", "unit": "V", "timestamp": "2024-01-15T08:00:00Z",
                                 "value": 1.5}]))
    assert load_file(path)[0].value == 1.5
    with pytest.raises(IngestError):
        read_json(io.StringIO('[{"device_id": "A", "value": 1}]'))


def test_group_batches():
    batches = group_batches(read_csv(io.StringIO(CSV)))
    assert list(batches) == [("PT-201", "pressure"), ("TT-101", "temp")]
    assert len(batches[("TT-101", "temp")]) == 2
