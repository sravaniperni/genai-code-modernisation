import json

import numpy as np
import pytest

from sensorpipe.calibration import (
    CalibrationCurve, GainChain, check_format_version, format_metadata, list_bundled_tables, load_bundled_table,
    load_calibration,
)
from sensorpipe.errors import CalibrationError


@pytest.fixture
def curve():
    return CalibrationCurve.from_points([(0.0, -0.5), (50.0, 49.0), (100.0, 101.0)], unit="degC")


def test_interpolates_between_points(curve):
    assert curve.apply(25.0) == pytest.approx(24.25)
    assert curve.apply(50.0) == pytest.approx(49.0)
    assert curve.apply(0.0) == pytest.approx(-0.5)


def test_out_of_range_and_extrapolation(curve):
    with pytest.raises(CalibrationError):
        curve.apply(120.0)
    wide = CalibrationCurve(curve.raw, curve.actual, extrapolate=True)
    assert wide.apply(-10.0) == pytest.approx(-10.4)
    assert wide.apply(110.0) == pytest.approx(111.4)


def test_apply_array(curve):
    out = curve.apply_array([25.0, 75.0])
    assert out.tolist() == pytest.approx([24.25, 75.0])
    with pytest.raises(CalibrationError):
        curve.apply_array([10.0, 500.0])


def test_curve_validation():
    with pytest.raises(CalibrationError):
        CalibrationCurve((1.0, 1.0), (0.0, 1.0))
    with pytest.raises(CalibrationError):
        CalibrationCurve((1.0,), (0.0,))


def test_gain_chain():
    chain = GainChain((("amplifier", 20.0), ("divider", 0.5), ("adc", 409.6)))
    assert chain.total_gain() == pytest.approx(4096.0)
    assert chain.cumulative() == pytest.approx({"amplifier": 20.0, "divider": 10.0, "adc": 4096.0})
    assert GainChain().total_gain() == 1.0


def test_load_calibration_file(tmp_path):
    path = tmp_path / "tt101.json"
    path.write_text(json.dumps({"format_version": "2.0.0", "sensor": "TT-101", "unit": "degC",
                                "points": [[4.0, 0.0], [20.0, 150.0]]}))
    curve = load_calibration(path)
    assert curve.name == "TT-101" and curve.apply(12.0) == pytest.approx(75.0)


def test_format_versions():
    assert check_format_version("2.1.0").major == 2
    for version in ["3.0.0", "2.2.0", "1.9.0", "2.0", "latest", None]:
        with pytest.raises(CalibrationError):
            check_format_version(version)


def test_format_metadata():
    assert format_metadata("2.1.0") == {"major": 2, "minor": 1, "patch": 0}


def test_bundled_tables():
    assert list_bundled_tables() == ["ntc10k", "pt100", "type_k"]
    pt100 = load_bundled_table("pt100")
    assert pt100.unit == "degC"
    assert pt100.apply(100.0) == pytest.approx(0.0)
    assert pt100.apply(110.0) == pytest.approx(25.773, abs=1e-3)
    assert np.allclose(load_bundled_table("type_k").apply_array([2.023, 4.096]), [50.0, 100.0])
    with pytest.raises(CalibrationError):
        load_bundled_table("pt9999")
