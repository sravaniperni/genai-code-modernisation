import numpy as np
import pytest

from sensorpipe.errors import UnitError
from sensorpipe.readings import Reading
from sensorpipe.units import convert, convert_reading, get_unit


def test_temperature_conversions():
    assert convert(20.0, "degC", "K") == pytest.approx(293.15)
    assert convert(293.15, "K", "degC") == pytest.approx(20.0)
    assert convert(212.0, "degF", "degC") == pytest.approx(100.0)
    assert convert(32.0, "degF", "K") == pytest.approx(273.15)


def test_pressure_conversions():
    assert convert(1.0, "bar", "kPa") == pytest.approx(100.0)
    assert convert(14.503774, "psi", "kPa") == pytest.approx(100.0, rel=1e-6)
    assert convert(1013.25, "mbar", "Pa") == pytest.approx(101325.0)


def test_flow_array_conversion_and_aliases():
    out = convert(np.array([0.0, 60.0, 120.0]), "L/min", "m3/h")
    assert out == pytest.approx([0.0, 3.6, 7.2])
    assert get_unit("°C").symbol == "degC"
    with pytest.raises(UnitError):
        get_unit("furlong")


def test_incompatible_dimensions_raise(make_readings):
    with pytest.raises(UnitError):
        convert(1.0, "bar", "degC")
    reading = make_readings([4.0], unit="mA")[0]
    converted = convert_reading(reading, "A")
    assert isinstance(converted, Reading) and converted.unit == "A" and converted.value == pytest.approx(0.004)
