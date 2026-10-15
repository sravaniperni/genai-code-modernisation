import pytest

from sensorpipe.anomaly import ZScoreDetector
from sensorpipe.errors import ConfigError
from sensorpipe.plugins import create_detector, discover_detectors

PLUGIN = """
from sensorpipe.anomaly import Anomaly, Detector


class StuckSensorDetector(Detector):
    name = "stuck"

    def __init__(self, repeats=3):
        self.repeats = repeats

    def detect(self, values):
        values = list(values)
        return [Anomaly(i, v, 1.0, "stuck") for i, v in enumerate(values)
                if i >= self.repeats and len(set(values[i - self.repeats:i + 1])) == 1]


NOT_A_DETECTOR = 42
"""


def test_builtins_without_plugins():
    detectors = discover_detectors()
    assert detectors["zscore"] is ZScoreDetector
    with pytest.raises(ConfigError, match="unknown detector"):
        create_detector("no-such-detector")


def test_plugin_detectors_are_discovered(plugin_dist):
    plugin_dist(
        {"stuck": "acme_stuck_a:StuckSensorDetector", "broken": "acme_missing_module:Nope",
         "bogus": "acme_stuck_a:NOT_A_DETECTOR", "zscore": "acme_stuck_a:StuckSensorDetector"},
        {"acme_stuck_a": PLUGIN},
    )
    detectors = discover_detectors()
    assert detectors["stuck"].__name__ == "StuckSensorDetector"
    assert "broken" not in detectors and "bogus" not in detectors
    assert detectors["zscore"] is ZScoreDetector
    found = create_detector("stuck", repeats=2).detect([1.0, 2.0, 2.0, 2.0])
    assert [a.index for a in found] == [3]
