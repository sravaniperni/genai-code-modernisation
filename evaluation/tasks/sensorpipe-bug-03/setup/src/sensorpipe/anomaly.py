"""Anomaly detection: z-score outliers, rolling bounds and device fault codes."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import numpy as np

#: Sentinel values that field devices report instead of a measurement.
DEFAULT_FAULT_CODES = (-9999.0, -999.0, 32767.0, 65535.0)


@dataclass(frozen=True)
class Anomaly:
    index: int
    value: float
    score: float
    reason: str


def zscores(values: Any) -> np.ndarray:
    """Standard scores of ``values``."""
    v = np.asarray(values, dtype=np.float_)
    if v.size < 2:
        return np.full(v.shape, np.NaN)
    mean, std = v.mean(), v.std()
    if std == 0:
        return np.zeros(v.shape)
    return (v - mean) / std


def zscore_anomalies(values: Any, threshold: float = 3.0) -> list[Anomaly]:
    v = np.asarray(values, dtype=np.float_)
    z = zscores(v)
    hits = np.flatnonzero(np.abs(np.nan_to_num(z, nan=0.0)) > threshold)
    return [Anomaly(int(i), float(v[i]), float(z[i]), "zscore") for i in hits]


def rolling_bounds(values: Any, window: int, k: float = 3.0) -> tuple[np.ndarray, np.ndarray]:
    """Bounds ``mean ± k·std`` of the previous ``window`` values (unbounded until enough history)."""
    if window < 2:
        raise ValueError("window must be at least 2")
    v = np.asarray(values, dtype=np.float_)
    lower = np.full(v.shape, -np.Inf)
    upper = np.full(v.shape, np.Inf)
    for i in range(window, v.size):
        hist = v[i - window : i]
        hist = hist[~np.isnan(hist)]
        if hist.size >= 2:
            mean, std = hist.mean(), hist.std()
            lower[i], upper[i] = mean - k * std, mean + k * std
    return lower, upper


def bound_anomalies(values: Any, window: int, k: float = 3.0) -> list[Anomaly]:
    v = np.asarray(values, dtype=np.float_)
    lower, upper = rolling_bounds(v, window, k)
    hits = np.flatnonzero((v < lower) | (v > upper))
    return [Anomaly(int(i), float(v[i]), float(v[i] - (upper[i] if v[i] > upper[i] else lower[i])), "bounds")
            for i in hits]


def fault_mask(values: Any, codes: Iterable[float] = DEFAULT_FAULT_CODES) -> np.ndarray:
    """Boolean mask of readings that are device fault sentinels."""
    return np.in1d(np.asarray(values, dtype=np.float_), np.asarray(list(codes), dtype=np.float_))


class Detector:
    """Base class for anomaly detectors (third-party detectors subclass this, see :mod:`sensorpipe.plugins`)."""

    name = "base"

    def detect(self, values: Any) -> list[Anomaly]:
        raise NotImplementedError


class ZScoreDetector(Detector):
    name = "zscore"

    def __init__(self, threshold: float = 3.0):
        self.threshold = threshold

    def detect(self, values: Any) -> list[Anomaly]:
        return zscore_anomalies(values, self.threshold)


class RollingBoundsDetector(Detector):
    name = "rolling"

    def __init__(self, window: int = 20, k: float = 3.0):
        self.window, self.k = window, k

    def detect(self, values: Any) -> list[Anomaly]:
        return bound_anomalies(values, self.window, self.k)


class FaultCodeDetector(Detector):
    name = "fault_code"

    def __init__(self, codes: Iterable[float] = DEFAULT_FAULT_CODES):
        self.codes = tuple(codes)

    def detect(self, values: Any) -> list[Anomaly]:
        v = np.asarray(values, dtype=np.float_)
        return [Anomaly(int(i), float(v[i]), 1.0, "fault_code") for i in np.flatnonzero(fault_mask(v, self.codes))]


BUILTIN_DETECTORS: dict[str, type[Detector]] = {
    cls.name: cls for cls in (ZScoreDetector, RollingBoundsDetector, FaultCodeDetector)
}
