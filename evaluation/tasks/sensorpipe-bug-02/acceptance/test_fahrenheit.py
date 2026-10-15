from datetime import datetime, timezone

import numpy as np
import pytest

from sensorpipe.readings import Reading
from sensorpipe.units import convert, convert_reading


@pytest.mark.parametrize("value, unit, expected", [
    (20.0, "degC", 68.0), (100.0, "degC", 212.0), (-40.0, "degC", -40.0), (0.0, "degC", 32.0),
    (300.0, "K", 80.33), (0.0, "K", -459.67), (68.0, "degF", 68.0),
])
def test_into_fahrenheit(value, unit, expected):
    assert convert(value, unit, "degF") == pytest.approx(expected, abs=1e-6)


def test_aliases_and_arrays():
    assert convert(37.0, "°C", "°F") == pytest.approx(98.6)
    assert convert(37.0, "C", "F") == pytest.approx(98.6)
    out = convert(np.array([-40.0, 0.0, 100.0]), "degC", "degF")
    assert out == pytest.approx([-40.0, 32.0, 212.0])


@pytest.mark.parametrize("value", [-459.67, -40.0, 0.0, 72.5, 1000.0])
def test_round_trip(value):
    assert convert(convert(value, "degF", "K"), "K", "degF") == pytest.approx(value, abs=1e-9)
    assert convert(convert(value, "degF", "degC"), "degC", "degF") == pytest.approx(value, abs=1e-9)


def test_convert_reading_to_fahrenheit():
    reading = Reading("TT-101", "temp", datetime(2024, 1, 15, 8, tzinfo=timezone.utc), 25.0, "degC")
    converted = convert_reading(reading, "°F")
    assert converted.unit == "degF" and converted.value == pytest.approx(77.0)


def test_other_units_unchanged():
    assert convert(25.0, "degC", "K") == pytest.approx(298.15)
    assert convert(298.15, "K", "degC") == pytest.approx(25.0)
    assert convert(2.0, "bar", "psi") == pytest.approx(29.0075, rel=1e-5)
    assert convert(500.0, "mbar", "kPa") == pytest.approx(50.0)
    assert convert(7.2, "m3/h", "L/min") == pytest.approx(120.0)
    assert convert(50.0, "%", "ratio") == pytest.approx(0.5)
