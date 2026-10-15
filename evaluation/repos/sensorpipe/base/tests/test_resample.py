import numpy as np
import pytest

from sensorpipe.readings import ReadingBatch
from sensorpipe.resample import batch_series, integrate, resample, window_stats


def test_resample_mean_with_gap():
    times = [5.0, 30.0, 70.0, 250.0]
    grid, values = resample(times, [1.0, 3.0, 5.0, 7.0], 60)
    assert grid.tolist() == [0.0, 60.0, 120.0, 180.0, 240.0]
    assert values[0] == 2.0 and values[1] == 5.0 and values[4] == 7.0
    assert np.isnan(values[2]) and np.isnan(values[3])
    _, values = resample([1.0, 2.0, 3.0], [4.0, 9.0, 2.0], 10, how="max")
    assert values.tolist() == [9.0]
    with pytest.raises(ValueError):
        resample([1.0], [1.0], 10, how="median-ish")


def test_window_stats_between_boundaries():
    times = np.arange(30.0, 1200.0, 60.0)
    values = np.arange(times.size, dtype=float)
    stats = window_stats(times, values, 600)
    assert [s.start for s in stats] == [0.0, 600.0]
    assert [s.count for s in stats] == [10, 10]
    assert stats[0].mean == pytest.approx(4.5) and stats[1].maximum == 19.0


def test_window_stats_skip_nan_and_empty_windows():
    stats = window_stats([10.0, 20.0, 1810.0], [1.0, np.nan, 3.0], 600)
    assert [(s.start, s.count) for s in stats] == [(0.0, 1), (1800.0, 1)]


def test_integrate_flow_to_volume():
    assert integrate([0.0, 60.0, 120.0], [1.0, 1.0, 2.0]) == pytest.approx(150.0)
    assert integrate([0.0], [1.0]) == 0.0


def test_series_validation(make_readings):
    with pytest.raises(ValueError):
        resample([2.0, 1.0], [1.0, 1.0], 10)
    with pytest.raises(ValueError):
        window_stats([1.0, 2.0], [1.0], 10)
    times, values = batch_series(ReadingBatch(make_readings([1.0, 2.0])))
    assert times.size == values.size == 2
