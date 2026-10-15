import json

import pytest

from sensorpipe.calibration import CalibrationCurve, load_bundled_table, load_calibration
from sensorpipe.errors import CalibrationError


@pytest.mark.parametrize("name, top, expected", [("pt100", 212.05, 300.0), ("type_k", 12.209, 300.0),
                                                 ("ntc10k", 33.62, 0.0)])
def test_top_point_of_bundled_tables(name, top, expected):
    curve = load_bundled_table(name)
    assert curve.apply(top) == pytest.approx(expected)
    assert curve.apply_array([top])[0] == pytest.approx(expected)


def test_bottom_and_interior_points():
    curve = load_bundled_table("pt100")
    assert curve.apply(80.31) == pytest.approx(-50.0)
    for raw, actual in zip(curve.raw, curve.actual):
        assert curve.apply(raw) == pytest.approx(actual)
    assert curve.apply(203.075) == pytest.approx(275.0)


def test_values_above_the_range():
    curve = CalibrationCurve.from_points([(4.0, 0.0), (12.0, 80.0), (20.0, 150.0)])
    assert curve.apply(20.0) == pytest.approx(150.0)
    with pytest.raises(CalibrationError):
        curve.apply(20.0001)
    wide = CalibrationCurve(curve.raw, curve.actual, extrapolate=True)
    assert wide.apply(20.0) == pytest.approx(150.0)
    assert wide.apply(24.0) == pytest.approx(185.0)
    assert wide.apply_array([20.0, 24.0, 2.0]).tolist() == pytest.approx([150.0, 185.0, -20.0])


def test_two_point_calibration_file(tmp_path):
    path = tmp_path / "pt-201.json"
    path.write_text(json.dumps({"format_version": "2.0.0", "sensor": "PT-201", "unit": "bar",
                                "points": [[4.0, 0.0], [20.0, 16.0]]}))
    curve = load_calibration(path)
    assert [curve.apply(x) for x in (4.0, 12.0, 20.0)] == pytest.approx([0.0, 8.0, 16.0])
