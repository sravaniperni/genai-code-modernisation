"""Resampling and windowed statistics over series of epoch seconds and values (gaps are NaN)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np

from sensorpipe.readings import ReadingBatch

_REDUCERS: dict[str, Callable[[np.ndarray], float]] = {
    "mean": np.mean,
    "min": np.min,
    "max": np.max,
    "sum": np.sum,
    "last": lambda a: a[-1],
}


@dataclass(frozen=True)
class WindowStat:
    """Statistics of one window ``[start, end)`` (epoch seconds)."""

    start: float
    end: float
    count: int
    mean: float
    minimum: float
    maximum: float
    std: float


def as_series(times: Any, values: Any) -> tuple[np.ndarray, np.ndarray]:
    """Validate and convert a time series to float arrays."""
    t = np.asarray(times, dtype=np.float_)
    v = np.asarray(values, dtype=np.float_)
    if t.ndim != 1 or t.shape != v.shape:
        raise ValueError("times and values must be one-dimensional arrays of equal length")
    if t.size > 1 and not np.alltrue(np.diff(t) > 0):
        raise ValueError("timestamps must be strictly increasing")
    return t, v


def batch_series(batch: ReadingBatch) -> tuple[np.ndarray, np.ndarray]:
    return as_series(batch.epochs(), batch.values())


def resample(times: Any, values: Any, interval: float, how: str = "mean") -> tuple[np.ndarray, np.ndarray]:
    """Aggregate onto a grid aligned to multiples of ``interval`` seconds; empty slots become NaN."""
    if interval <= 0:
        raise ValueError("interval must be positive")
    if how not in _REDUCERS:
        raise ValueError(f"unknown aggregation {how!r}; choose from {sorted(_REDUCERS)}")
    t, v = as_series(times, values)
    if t.size == 0:
        return np.array([], dtype=np.float_), np.array([], dtype=np.float_)
    start = np.floor(t[0] / interval) * interval
    slots = ((t - start) // interval).astype(int)
    grid = start + np.arange(slots[-1] + 1, dtype=np.float_) * interval
    out = np.full(grid.shape, np.NaN, dtype=np.float_)
    reducer = _REDUCERS[how]
    for slot in np.unique(slots):
        chunk = v[slots == slot]
        chunk = chunk[~np.isnan(chunk)]
        if chunk.size:
            out[slot] = reducer(chunk)
    return grid, out


def window_stats(times: Any, values: Any, width: float, start: float | None = None) -> list[WindowStat]:
    """Statistics over consecutive windows ``[start, start + width)``; empty windows are skipped.

    Windows are aligned to multiples of ``width`` unless an explicit ``start`` is given. NaN values are ignored.
    """
    if width <= 0:
        raise ValueError("width must be positive")
    t, v = as_series(times, values)
    if t.size == 0:
        return []
    lo = float(np.floor(t[0] / width) * width) if start is None else float(start)
    stats: list[WindowStat] = []
    while lo <= t[-1]:
        hi = lo + width
        mask = (t >= lo) & (t < hi) & ~np.isnan(v)
        chunk = v[mask]
        if chunk.size:
            stats.append(
                WindowStat(lo, hi, int(chunk.size), float(chunk.mean()), float(chunk.min()), float(chunk.max()),
                           float(chunk.std()))
            )
        lo = hi
    return stats


def integrate(times: Any, values: Any) -> float:
    """Trapezoidal integral over time in seconds (e.g. m3/s flow to m3 volume); NaN samples are skipped."""
    t, v = as_series(times, values)
    ok = ~np.isnan(v)
    if ok.sum() < 2:
        return 0.0
    return float(np.trapz(v[ok], t[ok]))
