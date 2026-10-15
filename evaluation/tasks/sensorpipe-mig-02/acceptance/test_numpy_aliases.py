import os
import re
from pathlib import Path

import numpy as np
import pytest

from sensorpipe.calibration import GainChain
from sensorpipe.resample import as_series, integrate, resample, window_stats


def test_gain_chain_totals():
    chain = GainChain((("amplifier", 20.0), ("divider", 0.5), ("adc", 409.6)))
    assert chain.total_gain() == pytest.approx(4096.0)
    assert isinstance(chain.total_gain(), float)
    assert chain.cumulative() == pytest.approx({"amplifier": 20.0, "divider": 10.0, "adc": 4096.0})
    assert list(chain.cumulative()) == ["amplifier", "divider", "adc"]


def test_empty_and_single_stage_chains():
    assert GainChain().total_gain() == 1.0
    assert GainChain().cumulative() == {}
    assert GainChain((("shunt", 0.25),)).cumulative() == {"shunt": 0.25}


def test_series_validation():
    t, v = as_series([0.0, 1.0, 5.0], [1.0, 2.0, 3.0])
    assert t.tolist() == [0.0, 1.0, 5.0]
    assert as_series([], [])[0].size == 0
    with pytest.raises(ValueError):
        as_series([0.0, 2.0, 1.0], [1.0, 2.0, 3.0])
    with pytest.raises(ValueError):
        as_series([0.0, 1.0, 1.0], [1.0, 2.0, 3.0])


def test_resampling_paths():
    grid, values = resample([5.0, 30.0, 70.0], [1.0, 3.0, 5.0], 60)
    assert grid.tolist() == [0.0, 60.0] and values.tolist() == [2.0, 5.0]
    stats = window_stats(np.arange(30.0, 1200.0, 60.0), np.arange(20.0), 600)
    assert [s.count for s in stats] == [10, 10]
    assert integrate([0.0, 60.0, 120.0], [1.0, 1.0, 2.0]) == pytest.approx(150.0)
    with pytest.raises(ValueError):
        window_stats([3.0, 2.0], [1.0, 1.0], 60)


def test_deprecated_aliases_are_gone():
    src = Path(os.environ.get("REPO_ROOT", ".")) / "src"
    pattern = re.compile(r"\b(?:np|numpy)\.(?:product|cumproduct|alltrue|sometrue)\b")
    offenders = [f"{p}: {m.group(0)}" for p in src.rglob("*.py") for m in pattern.finditer(p.read_text())]
    assert offenders == []
