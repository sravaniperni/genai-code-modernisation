"""Engineering unit conversion. Each unit is an affine transform to its dimension's base unit:
``base = value * scale + offset`` (kelvin, pascal, cubic metres per second, volt, ampere, ratio)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeVar

import numpy as np

from sensorpipe.errors import UnitError
from sensorpipe.readings import Reading

T = TypeVar("T", float, np.ndarray)


@dataclass(frozen=True)
class Unit:
    symbol: str
    dimension: str
    scale: float
    offset: float = 0.0

    def to_base(self, value: T) -> T:
        return value * self.scale + self.offset

    def from_base(self, value: T) -> T:
        return value / self.scale - self.offset


_UNITS = {
    u.symbol: u
    for u in (
        Unit("K", "temperature", 1.0),
        Unit("degC", "temperature", 1.0, 273.15),
        Unit("degF", "temperature", 5.0 / 9.0, 273.15 - 32.0 * 5.0 / 9.0),
        Unit("Pa", "pressure", 1.0),
        Unit("kPa", "pressure", 1e3),
        Unit("mbar", "pressure", 1e2),
        Unit("bar", "pressure", 1e5),
        Unit("psi", "pressure", 6894.757293168),
        Unit("m3/s", "flow", 1.0),
        Unit("m3/h", "flow", 1.0 / 3600.0),
        Unit("L/min", "flow", 1.0 / 60000.0),
        Unit("V", "voltage", 1.0),
        Unit("mV", "voltage", 1e-3),
        Unit("A", "current", 1.0),
        Unit("mA", "current", 1e-3),
        Unit("ratio", "ratio", 1.0),
        Unit("%", "ratio", 1e-2),
    )
}
_ALIASES = {"°C": "degC", "C": "degC", "°F": "degF", "F": "degF", "kelvin": "K", "m³/h": "m3/h", "l/min": "L/min"}


def get_unit(symbol: str) -> Unit:
    """Look up a unit by symbol or common alias."""
    key = _ALIASES.get(symbol.strip(), symbol.strip())
    try:
        return _UNITS[key]
    except KeyError:
        raise UnitError(f"unknown unit {symbol!r}") from None


def convert(value: T, from_unit: str, to_unit: str) -> T:
    """Convert a scalar or numpy array between units of the same dimension."""
    src, dst = get_unit(from_unit), get_unit(to_unit)
    if src.dimension != dst.dimension:
        raise UnitError(f"cannot convert {src.dimension} ({src.symbol}) to {dst.dimension} ({dst.symbol})")
    if src == dst:
        return value
    return dst.from_base(src.to_base(value))


def convert_reading(reading: Reading, to_unit: str) -> Reading:
    target = get_unit(to_unit).symbol
    return reading.with_value(convert(reading.value, reading.unit, target), target)
