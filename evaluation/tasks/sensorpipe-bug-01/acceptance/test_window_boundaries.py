import numpy as np
import pytest

from sensorpipe.resample import window_stats


def test_boundary_readings_are_counted_once():
    times = np.arange(0.0, 1201.0, 60.0)
    values = np.arange(times.size, dtype=float)
    stats = window_stats(times, values, 600)
    assert [(s.start, s.end) for s in stats] == [(0.0, 600.0), (600.0, 1200.0), (1200.0, 1800.0)]
    assert [s.count for s in stats] == [10, 10, 1]
    assert sum(s.count for s in stats) == times.size


def test_window_statistics_use_only_their_own_readings():
    times = np.arange(0.0, 1201.0, 60.0)
    values = np.arange(times.size, dtype=float)
    first, second, last = window_stats(times, values, 600)
    assert first.mean == pytest.approx(4.5) and first.maximum == 9.0 and first.minimum == 0.0
    assert second.mean == pytest.approx(14.5) and second.minimum == 10.0 and second.maximum == 19.0
    assert last.mean == 20.0 and last.count == 1
    assert first.std == pytest.approx(np.arange(10.0).std())


def test_reading_at_window_start_belongs_to_that_window():
    stats = window_stats([600.0, 1199.0], [5.0, 7.0], 600)
    assert [(s.start, s.count) for s in stats] == [(600.0, 2)]
    stats = window_stats([599.0, 600.0], [1.0, 9.0], 600)
    assert [(s.start, s.count, s.maximum) for s in stats] == [(0.0, 1, 1.0), (600.0, 1, 9.0)]


def test_explicit_start_offsets():
    times = np.arange(300.0, 2101.0, 300.0)
    stats = window_stats(times, np.ones(times.size), 900, start=300.0)
    assert [(s.start, s.count) for s in stats] == [(300.0, 3), (1200.0, 3), (2100.0, 1)]


def test_volume_from_windows_matches_readings():
    times = np.arange(0.0, 3601.0, 60.0)
    flow = np.full(times.size, 2.0)
    stats = window_stats(times, flow, 900)
    assert sum(s.count * s.mean for s in stats) == pytest.approx(flow.sum())
