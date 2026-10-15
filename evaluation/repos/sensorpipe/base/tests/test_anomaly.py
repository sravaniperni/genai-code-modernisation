import numpy as np

from sensorpipe.anomaly import (
    BUILTIN_DETECTORS, FaultCodeDetector, ZScoreDetector, fault_mask, rolling_bounds, zscore_anomalies, zscores,
)


def test_zscore_flags_spike():
    values = [10.0] * 19 + [30.0]
    found = zscore_anomalies(values, threshold=3.0)
    assert [a.index for a in found] == [19]
    assert found[0].reason == "zscore" and found[0].value == 30.0
    assert zscores([5.0, 5.0, 5.0]).tolist() == [0.0, 0.0, 0.0]
    assert np.isnan(zscores([1.0])).all()


def test_rolling_bounds():
    values = np.array([1.0, 2.0, 1.0, 2.0, 1.0, 9.0])
    lower, upper = rolling_bounds(values, window=4, k=2.0)
    assert np.isinf(upper[:4]).all()
    assert lower[4] < 1.0 < upper[4] and values[5] > upper[5]


def test_fault_codes():
    assert fault_mask([1.0, -9999.0, 32767.0, 5.0]).tolist() == [False, True, True, False]
    assert [a.index for a in FaultCodeDetector().detect([0.0, 65535.0])] == [1]


def test_builtin_detectors():
    assert set(BUILTIN_DETECTORS) == {"zscore", "rolling", "fault_code"}
    assert [a.index for a in ZScoreDetector(threshold=1.5).detect([1.0, 1.0, 1.0, 1.0, 8.0])] == [4]
    assert BUILTIN_DETECTORS["rolling"](window=3, k=1.0).detect([1.0, 1.1, 0.9, 1.0, 5.0])[0].index == 4
