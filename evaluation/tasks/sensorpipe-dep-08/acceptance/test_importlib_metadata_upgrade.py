import importlib.metadata
import itertools
import logging

import pytest

from sensorpipe.anomaly import BUILTIN_DETECTORS, Detector, ZScoreDetector
from sensorpipe.errors import ConfigError
from sensorpipe.plugins import ENTRY_POINT_GROUP, create_detector, discover_detectors

_ids = itertools.count()

PLUGIN = """
from sensorpipe.anomaly import Anomaly, Detector


class {name}(Detector):
    name = "{ep}"

    def __init__(self, limit=100.0):
        self.limit = limit

    def detect(self, values):
        return [Anomaly(i, v, v - self.limit, "{ep}") for i, v in enumerate(values) if v > self.limit]


NOT_A_DETECTOR = 42
"""


@pytest.fixture
def install(tmp_path, monkeypatch):
    def _install(entries, module_sources):
        n = next(_ids)
        root = tmp_path / f"site{n}"
        info = root / f"vendor_plugins_{n}-2.0.dist-info"
        info.mkdir(parents=True)
        (info / "METADATA").write_text(f"Metadata-Version: 2.1\nName: vendor-plugins-{n}\nVersion: 2.0\n")
        body = "\n".join(f"{name} = {target}" for name, target in entries.items())
        (info / "entry_points.txt").write_text(f"[{ENTRY_POINT_GROUP}]\n{body}\n\n[console_scripts]\nvp{n} = os:getcwd\n")
        for module, source in module_sources.items():
            (root / f"{module}.py").write_text(source)
        monkeypatch.syspath_prepend(str(root))

    return _install


def test_importlib_metadata_is_pinned_to_7_2_1():
    assert importlib.metadata.version("importlib-metadata") == "7.2.1"


def test_builtins_only():
    detectors = discover_detectors()
    assert {k: v for k, v in detectors.items() if k in BUILTIN_DETECTORS} == BUILTIN_DETECTORS
    assert isinstance(create_detector("zscore", threshold=2.0), ZScoreDetector)


def test_plugins_from_several_distributions(install):
    n = next(_ids)
    install({"overlimit": f"vp_over_{n}:OverLimit"}, {f"vp_over_{n}": PLUGIN.format(name="OverLimit", ep="overlimit")})
    install({"spike": f"vp_spike_{n}:Spike"}, {f"vp_spike_{n}": PLUGIN.format(name="Spike", ep="spike")})
    detectors = discover_detectors()
    assert {"overlimit", "spike"} <= set(detectors)
    assert issubclass(detectors["spike"], Detector)
    found = create_detector("overlimit", limit=50.0).detect([10.0, 60.0, 49.0])
    assert [(a.index, a.reason) for a in found] == [(1, "overlimit")]


def test_invalid_plugins_are_skipped(install, caplog):
    n = next(_ids)
    module = f"vp_mixed_{n}"
    install(
        {"good": f"{module}:Good", "missing": f"vp_does_not_exist_{n}:Nope", "constant": f"{module}:NOT_A_DETECTOR",
         "zscore": f"{module}:Good"},
        {module: PLUGIN.format(name="Good", ep="good")},
    )
    with caplog.at_level(logging.WARNING, logger="sensorpipe.plugins"):
        detectors = discover_detectors()
    assert "good" in detectors
    assert "missing" not in detectors and "constant" not in detectors
    assert detectors["zscore"] is ZScoreDetector
    messages = " ".join(r.getMessage() for r in caplog.records)
    assert "missing" in messages and "constant" in messages and "zscore" in messages


def test_unknown_detector_lists_available(install):
    n = next(_ids)
    install({"overlimit": f"vp_list_{n}:OverLimit"}, {f"vp_list_{n}": PLUGIN.format(name="OverLimit", ep="overlimit")})
    with pytest.raises(ConfigError) as excinfo:
        create_detector("does-not-exist")
    assert "overlimit" in str(excinfo.value) and "zscore" in str(excinfo.value)
