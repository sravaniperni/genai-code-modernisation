import numpy as np
import pytest

from sensorpipe.anomaly import ZScoreDetector, zscore_anomalies, zscores
from sensorpipe.resample import resample


def series():
    return [10.0] * 18 + [np.nan, 30.0]


def test_spike_is_flagged_despite_dropout():
    found = zscore_anomalies(series(), threshold=3.0)
    assert [a.index for a in found] == [19]
    assert found[0].value == 30.0 and found[0].score > 3.0


def test_scores_ignore_dropouts():
    values = series()
    scores = zscores(values)
    clean = zscores([v for v in values if not np.isnan(v)])
    assert np.isnan(scores[18])
    assert np.concatenate([scores[:18], scores[19:]]) == pytest.approx(clean)


def test_dropouts_are_never_anomalies():
    values = [np.nan, 1.0, 1.2, np.nan, 0.9, 1.1, 1.0, 6.0, np.nan]
    found = ZScoreDetector(threshold=2.0).detect(values)
    assert [a.index for a in found] == [7]
    assert not any(np.isnan(a.value) for a in found)


def test_degenerate_inputs():
    assert zscore_anomalies([np.nan, np.nan, np.nan]) == []
    assert np.isnan(zscores([np.nan, 4.0])).all()
    assert zscores([2.0, np.nan, 2.0]).tolist()[0::2] == [0.0, 0.0]


def test_resampled_gaps_do_not_hide_spikes():
    times = [0.0, 60.0, 120.0, 300.0, 360.0, 420.0, 480.0, 540.0, 600.0, 660.0, 720.0, 780.0]
    values = [5.0, 5.1, 4.9, 5.0, 5.2, 4.8, 5.0, 5.1, 25.0, 5.0, 4.9, 5.0]
    _, resampled = resample(times, values, 60)
    assert np.isnan(resampled).sum() == 2
    found = ZScoreDetector(threshold=2.5).detect(resampled)
    assert [int(a.index) for a in found] == [10]
