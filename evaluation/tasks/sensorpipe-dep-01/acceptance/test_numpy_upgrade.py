import importlib.metadata
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from sensorpipe.anomaly import (
    BUILTIN_DETECTORS, FaultCodeDetector, RollingBoundsDetector, fault_mask, rolling_bounds, zscore_anomalies, zscores,
)
from sensorpipe.calibration import CalibrationCurve, GainChain
from sensorpipe.readings import Reading, ReadingBatch
from sensorpipe.resample import as_series, integrate, resample, window_stats

UTC = timezone.utc


def test_numpy_is_pinned_to_2_2_6():
    assert importlib.metadata.version("numpy") == "2.2.6"
    assert np.__version__ == "2.2.6"


def test_reading_batch_arrays():
    start = datetime(2024, 5, 1, 6, 0, tzinfo=UTC)
    batch = ReadingBatch(Reading("FT-1", "flow", start + timedelta(seconds=30 * i), v, "m3/s")
                         for i, v in enumerate([0.5, np.nan, 0.7]))
    values, epochs = batch.values(), batch.epochs()
    assert values.dtype == np.float64 and epochs.dtype == np.float64
    assert np.isnan(values[1]) and values[2] == 0.7
    assert np.diff(epochs).tolist() == [30.0, 30.0]


def test_resample_and_window_statistics():
    grid, values = resample([5.0, 30.0, 70.0, 250.0], [1.0, 3.0, 5.0, 7.0], 60)
    assert grid.dtype == np.float64
    assert grid.tolist() == [0.0, 60.0, 120.0, 180.0, 240.0]
    assert values[[0, 1, 4]].tolist() == [2.0, 5.0, 7.0]
    assert np.isnan(values[2]) and np.isnan(values[3])
    _, maxima = resample([1.0, 2.0, 61.0], [4.0, 9.0, np.nan], 60, how="max")
    assert maxima[0] == 9.0 and np.isnan(maxima[1])
    stats = window_stats(np.arange(30.0, 1200.0, 60.0), np.arange(20.0), 600)
    assert [(s.start, s.count, s.mean, s.maximum) for s in stats] == [(0.0, 10, 4.5, 9.0), (600.0, 10, 14.5, 19.0)]
    assert stats[0].std == pytest.approx(np.arange(10.0).std())


def test_series_validation_still_rejects_unordered_input():
    with pytest.raises(ValueError):
        as_series([0.0, 10.0, 5.0], [1.0, 2.0, 3.0])
    with pytest.raises(ValueError):
        resample([2.0, 1.0], [1.0, 1.0], 10)
    t, v = as_series([0.0, 1.0], [1, 2])
    assert t.dtype == np.float64 and v.dtype == np.float64


def test_integration():
    assert integrate([0.0, 60.0, 120.0], [1.0, 1.0, 2.0]) == pytest.approx(150.0)
    assert integrate([0.0, 60.0, 90.0, 120.0], [1.0, 1.0, np.nan, 2.0]) == pytest.approx(150.0)
    assert integrate([0.0], [1.0]) == 0.0
    assert isinstance(integrate([0.0, 1.0], [1.0, 1.0]), float)


def test_calibration_and_gain_chain():
    curve = CalibrationCurve.from_points([(0.0, -0.5), (50.0, 49.0), (100.0, 101.0)], extrapolate=True)
    out = curve.apply_array([25.0, 75.0, 110.0])
    assert out.dtype == np.float64
    assert out.tolist() == pytest.approx([24.25, 75.0, 111.4])
    chain = GainChain((("amplifier", 20.0), ("divider", 0.5), ("adc", 409.6)))
    assert chain.total_gain() == pytest.approx(4096.0)
    assert isinstance(chain.total_gain(), float)
    assert chain.cumulative() == pytest.approx({"amplifier": 20.0, "divider": 10.0, "adc": 4096.0})
    assert GainChain().total_gain() == 1.0 and GainChain().cumulative() == {}


def test_anomaly_detection():
    values = [10.0] * 19 + [30.0]
    assert [a.index for a in zscore_anomalies(values)] == [19]
    scores = zscores([1.0, np.nan, 3.0])
    assert np.isnan(scores[1]) and scores[[0, 2]].tolist() == [-1.0, 1.0]
    lower, upper = rolling_bounds(np.array([1.0, 2.0, 1.0, 2.0, 1.0, 9.0]), window=4, k=2.0)
    assert np.isneginf(lower[:4]).all() and np.isposinf(upper[:4]).all()
    assert upper[5] == pytest.approx(2.5)
    assert [a.index for a in RollingBoundsDetector(window=3, k=1.0).detect([1.0, 1.1, 0.9, 1.0, 5.0])] == [4]
    assert fault_mask([1.0, -9999.0, 32767.0, 5.0]).tolist() == [False, True, True, False]
    assert [a.index for a in FaultCodeDetector().detect([0.0, 65535.0])] == [1]
    assert set(BUILTIN_DETECTORS) == {"zscore", "rolling", "fault_code"}
