"""Calibration curves, signal-conditioning gain chains and calibration files.

Calibration files are JSON documents with a semantic ``format_version``; bundled reference tables (RTD,
thermocouple and thermistor curves) ship as CSV resources in :mod:`sensorpipe.tables`."""

from __future__ import annotations

import bisect
import csv
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

import numpy as np
import semver

from sensorpipe.errors import CalibrationError

#: Newest calibration file format understood by this release (same major version required).
FORMAT_VERSION = "2.1.0"
_TABLE_PACKAGE = "sensorpipe.tables"


@dataclass(frozen=True)
class CalibrationCurve:
    """Piecewise-linear mapping from raw sensor values to engineering values."""

    raw: tuple[float, ...]
    actual: tuple[float, ...]
    unit: str = ""
    name: str = ""
    extrapolate: bool = False

    def __post_init__(self) -> None:
        if len(self.raw) != len(self.actual) or len(self.raw) < 2:
            raise CalibrationError("a calibration curve needs at least two (raw, actual) points")
        if any(b <= a for a, b in zip(self.raw, self.raw[1:])):
            raise CalibrationError("calibration raw points must be strictly increasing")

    @classmethod
    def from_points(cls, points: Iterable[tuple[float, float]], **kwargs: Any) -> CalibrationCurve:
        pairs = sorted((float(r), float(a)) for r, a in points)
        return cls(tuple(r for r, _ in pairs), tuple(a for _, a in pairs), **kwargs)

    @property
    def range(self) -> tuple[float, float]:
        return self.raw[0], self.raw[-1]

    def apply(self, value: float) -> float:
        """Calibrate one raw value."""
        lo, hi = self.range
        if value < lo or value > hi:
            if not self.extrapolate:
                raise CalibrationError(f"value {value} outside calibrated range [{lo}, {hi}]")
            i = 1 if value < lo else len(self.raw) - 1
        else:
            i = max(1, bisect.bisect_left(self.raw, value))
        x0, x1 = self.raw[i - 1], self.raw[i]
        y0, y1 = self.actual[i - 1], self.actual[i]
        return y0 + (value - x0) * (y1 - y0) / (x1 - x0)

    def apply_array(self, values: Any) -> np.ndarray:
        """Calibrate an array of raw values; NaN stays NaN."""
        arr = np.asarray(values, dtype=np.float_)
        lo, hi = self.range
        outside = (arr < lo) | (arr > hi)
        if outside.any() and not self.extrapolate:
            raise CalibrationError(f"{int(outside.sum())} value(s) outside calibrated range [{lo}, {hi}]")
        out = np.interp(arr, self.raw, self.actual)
        if outside.any():
            out[outside] = [self.apply(float(v)) for v in arr[outside]]
        return out


@dataclass(frozen=True)
class GainChain:
    """Signal-conditioning stages (amplifier, divider, ADC scaling) with multiplicative gains."""

    stages: tuple[tuple[str, float], ...] = ()

    def total_gain(self) -> float:
        return float(np.product([gain for _, gain in self.stages]))

    def cumulative(self) -> dict[str, float]:
        """Gain from the sensor up to and including each stage."""
        if not self.stages:
            return {}
        gains = np.cumproduct([gain for _, gain in self.stages])
        return {name: float(g) for (name, _), g in zip(self.stages, gains)}


def check_format_version(text: Any) -> semver.Version:
    """Validate a calibration ``format_version`` and return it parsed."""
    if not isinstance(text, str) or not semver.Version.is_valid(text):
        raise CalibrationError(f"invalid calibration format version {text!r}")
    version = semver.Version.parse(text)
    supported = semver.Version.parse(FORMAT_VERSION)
    if version.major != supported.major or version > supported:
        raise CalibrationError(f"calibration format {text} is not supported (this release reads up to {FORMAT_VERSION})")
    return version


def format_metadata(text: str) -> dict[str, Any]:
    """Describe a calibration format version for report headers."""
    info = check_format_version(text).to_dict()
    return {key: value for key, value in info.items() if value is not None}


def parse_calibration(data: Mapping[str, Any]) -> CalibrationCurve:
    """Build a curve from a decoded calibration document."""
    check_format_version(data.get("format_version"))
    try:
        points = [(p[0], p[1]) for p in data["points"]]
        return CalibrationCurve.from_points(
            points, unit=str(data.get("unit", "")), name=str(data.get("sensor", "")),
            extrapolate=bool(data.get("extrapolate", False)),
        )
    except (KeyError, TypeError, IndexError) as exc:
        raise CalibrationError(f"malformed calibration document: {exc!r}") from exc


def load_calibration(path: str | Path) -> CalibrationCurve:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CalibrationError(f"cannot read calibration file {path}: {exc}") from exc
    return parse_calibration(data)


def parse_table(lines: Iterable[str], name: str = "") -> CalibrationCurve:
    """Parse a CSV calibration table with ``# key: value`` header comments."""
    meta: dict[str, str] = {}
    rows: list[str] = []
    for line in lines:
        line = line.strip()
        if line.startswith("#"):
            key, sep, value = line[1:].partition(":")
            if sep:
                meta[key.strip()] = value.strip()
        elif line:
            rows.append(line)
    check_format_version(meta.get("format_version"))
    try:
        points = [(float(r["raw"]), float(r["actual"])) for r in csv.DictReader(rows)]
    except (KeyError, ValueError) as exc:
        raise CalibrationError(f"malformed calibration table {name!r}: {exc}") from exc
    return CalibrationCurve.from_points(points, unit=meta.get("unit", ""), name=name)


def list_bundled_tables() -> list[str]:
    """Names of the reference tables shipped with sensorpipe."""
    return sorted(entry[:-4] for entry in resources.contents(_TABLE_PACKAGE) if entry.endswith(".csv"))


def load_bundled_table(name: str) -> CalibrationCurve:
    resource = f"{name}.csv"
    if not resources.is_resource(_TABLE_PACKAGE, resource):
        raise CalibrationError(f"no bundled calibration table named {name!r}")
    with resources.open_text(_TABLE_PACKAGE, resource, encoding="utf-8") as handle:
        return parse_table(handle, name=name)
