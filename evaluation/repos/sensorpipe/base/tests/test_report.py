import csv
import io
import json
from datetime import datetime, timezone

import numpy as np
import pytest

from sensorpipe.readings import ReadingBatch
from sensorpipe.report import export_csv, export_json, report_filename, summarise

UTC = timezone.utc


@pytest.fixture
def summary(make_readings):
    return summarise(ReadingBatch(make_readings([20.0, np.nan, 22.0], start=datetime(2024, 3, 10, 11, 30, tzinfo=UTC))),
                     anomalies=1)


def test_summarise(summary):
    assert summary.count == 3 and summary.mean == pytest.approx(21.0)
    assert (summary.minimum, summary.maximum) == (20.0, 22.0)
    assert summary.first == datetime(2024, 3, 10, 11, 30, tzinfo=UTC)
    with pytest.raises(ValueError):
        summarise(ReadingBatch())


def test_export_csv(summary):
    rows = list(csv.DictReader(io.StringIO(export_csv([summary]))))
    assert rows[0]["device_id"] == "TT-101" and rows[0]["anomalies"] == "1"
    assert rows[0]["first_epoch"] == "1710070200" and rows[0]["last_epoch"] == "1710070320"


def test_export_json(summary):
    payload = json.loads(export_json([summary], datetime(2024, 3, 10, 12, 0, tzinfo=UTC), calibration_format="2.0.0"))
    assert payload["generated_epoch"] == 1710072000
    assert payload["channels"][0]["mean"] == 21.0
    assert payload["calibration_format"] == {"major": 2, "minor": 0, "patch": 0}


def test_report_filename():
    assert report_filename(datetime(2024, 3, 10, 11, 30, tzinfo=UTC)) == "sensorpipe-report-1710070200.csv"
    assert report_filename(datetime(2024, 3, 10, 11, 30, tzinfo=UTC), "json", "daily") == "daily-1710070200.json"
