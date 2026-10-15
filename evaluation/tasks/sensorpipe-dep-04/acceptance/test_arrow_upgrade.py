import csv
import importlib.metadata
import io
import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from sensorpipe.readings import Reading, ReadingBatch, parse_timestamp
from sensorpipe.report import export_csv, export_json, report_filename, summarise
from sensorpipe.timeutil import epoch_seconds, floor_time, format_local

UTC = timezone.utc


def test_arrow_is_pinned_to_1_3_0():
    assert importlib.metadata.version("arrow") == "1.3.0"


def test_epoch_seconds_are_whole_integers():
    value = epoch_seconds(datetime(2024, 3, 10, 11, 30, 0, 750000, tzinfo=UTC))
    assert value == 1710070200 and type(value) is int
    assert epoch_seconds(datetime(2024, 3, 10, 12, 30, tzinfo=ZoneInfo("Europe/Berlin"))) == 1710070200
    assert epoch_seconds(datetime(1970, 1, 1, tzinfo=UTC)) == 0


def test_floor_time():
    value = datetime(2024, 3, 10, 11, 47, 13, 500000, tzinfo=UTC)
    assert floor_time(value, 900) == datetime(2024, 3, 10, 11, 45, tzinfo=UTC)
    assert floor_time(value, 86400) == datetime(2024, 3, 10, tzinfo=UTC)
    with pytest.raises(ValueError):
        floor_time(value, 0)


def test_local_formatting_and_custom_parsing():
    assert format_local(datetime(2024, 1, 15, 12, 0, tzinfo=UTC), "Europe/Berlin") == "2024-01-15 13:00"
    assert format_local(datetime(2024, 1, 15, 12, 0, tzinfo=UTC), "UTC", "DD.MM.YYYY HH:mm:ss") == "15.01.2024 12:00:00"
    ts = parse_timestamp("15.01.2024 09:30:00", tz="Europe/Berlin", fmt="DD.MM.YYYY HH:mm:ss")
    assert ts == datetime(2024, 1, 15, 8, 30, tzinfo=UTC)


def test_report_file_names_use_integer_epochs():
    assert report_filename(datetime(2024, 3, 10, 11, 30, tzinfo=UTC)) == "sensorpipe-report-1710070200.csv"
    assert report_filename(datetime(2024, 3, 10, 11, 30, 0, 250000, tzinfo=UTC), "json") == \
        "sensorpipe-report-1710070200.json"
    assert report_filename(datetime(2024, 3, 10, 12, 30, tzinfo=ZoneInfo("Europe/Berlin")), "csv", "daily") == \
        "daily-1710070200.csv"


@pytest.fixture
def summary():
    start = datetime(2024, 3, 10, 11, 30, 0, 400000, tzinfo=UTC)
    readings = [Reading("TT-101", "temp", start + timedelta(minutes=i), v, "degC") for i, v in enumerate([20.0, 22.0])]
    return summarise(ReadingBatch(readings), anomalies=0)


def test_csv_export_epochs(summary):
    (row,) = list(csv.DictReader(io.StringIO(export_csv([summary]))))
    assert row["first_epoch"] == "1710070200" and row["last_epoch"] == "1710070260"
    assert row["first"] == "2024-03-10T11:30:00.400000+00:00"


def test_json_export_epochs(summary):
    payload = json.loads(export_json([summary], datetime(2024, 3, 10, 12, 0, 0, 900000, tzinfo=UTC)))
    assert payload["generated_epoch"] == 1710072000
    assert payload["channels"][0]["first_epoch"] == 1710070200
    assert payload["channels"][0]["last_epoch"] == 1710070260
