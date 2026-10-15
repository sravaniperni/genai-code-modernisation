import importlib.metadata
import json
from datetime import datetime, timedelta, timezone

import pytest

from sensorpipe.calibration import (
    check_format_version, format_metadata, load_bundled_table, load_calibration, parse_table,
)
from sensorpipe.errors import CalibrationError
from sensorpipe.readings import Reading, ReadingBatch
from sensorpipe.report import export_json, summarise

UTC = timezone.utc


def test_semver_is_pinned_to_3_0_4():
    assert importlib.metadata.version("semver") == "3.0.4"


@pytest.mark.parametrize("text", ["2.0.0", "2.1.0", "2.0.7", "2.1.0-rc.1", "2.0.0+build.5"])
def test_supported_format_versions(text):
    version = check_format_version(text)
    assert str(version) == text
    assert version.major == 2


@pytest.mark.parametrize("text", ["3.0.0", "2.2.0", "2.1.1", "1.9.9", "2.0", "v2.0.0", "latest", "", None, 2])
def test_rejected_format_versions(text):
    with pytest.raises(CalibrationError):
        check_format_version(text)


def test_format_metadata():
    assert format_metadata("2.1.0") == {"major": 2, "minor": 1, "patch": 0}
    assert format_metadata("2.1.0-rc.1+build.5") == {
        "major": 2, "minor": 1, "patch": 0, "prerelease": "rc.1", "build": "build.5",
    }
    with pytest.raises(CalibrationError):
        format_metadata("4.0.0")


def test_calibration_files_and_tables(tmp_path):
    path = tmp_path / "tt101.json"
    path.write_text(json.dumps({"format_version": "2.1.0", "sensor": "TT-101", "unit": "degC",
                                "points": [[4.0, 0.0], [20.0, 150.0]]}))
    assert load_calibration(path).apply(12.0) == pytest.approx(75.0)
    path.write_text(json.dumps({"format_version": "3.0.0", "points": [[4.0, 0.0], [20.0, 150.0]]}))
    with pytest.raises(CalibrationError):
        load_calibration(path)
    assert load_bundled_table("ntc10k").apply(10.0) == pytest.approx(25.0)
    with pytest.raises(CalibrationError):
        parse_table(["# format_version: next", "raw,actual", "0,0", "1,1"])


def test_json_report_metadata():
    start = datetime(2024, 3, 10, 11, 30, tzinfo=UTC)
    batch = ReadingBatch([Reading("TT-101", "temp", start + timedelta(minutes=i), 20.0 + i, "degC") for i in range(3)])
    payload = json.loads(export_json([summarise(batch)], start, calibration_format="2.1.0-rc.2"))
    assert payload["calibration_format"] == {"major": 2, "minor": 1, "patch": 0, "prerelease": "rc.2"}
