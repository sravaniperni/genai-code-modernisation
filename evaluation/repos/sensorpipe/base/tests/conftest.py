from datetime import datetime, timedelta, timezone

import pytest

from sensorpipe.readings import Reading

UTC = timezone.utc


@pytest.fixture
def make_readings():
    def _make(values, start=datetime(2024, 1, 15, 8, 0, 30, tzinfo=UTC), step=60, device="TT-101",
              channel="temp", unit="degC"):
        return [Reading(device, channel, start + timedelta(seconds=i * step), float(v), unit)
                for i, v in enumerate(values)]

    return _make


@pytest.fixture
def plugin_dist(tmp_path, monkeypatch):
    """Create an installed-looking distribution that registers detector entry points."""
    counter = iter(range(1000))

    def _make(entries, modules):
        n = next(counter)
        root = tmp_path / f"site{n}"
        info = root / f"acme_detectors_{n}-1.0.dist-info"
        info.mkdir(parents=True)
        (info / "METADATA").write_text(f"Metadata-Version: 2.1\nName: acme-detectors-{n}\nVersion: 1.0\n")
        lines = ["[sensorpipe.detectors]"] + [f"{name} = {target}" for name, target in entries.items()]
        (info / "entry_points.txt").write_text("\n".join(lines) + "\n")
        for module, source in modules.items():
            (root / f"{module}.py").write_text(source)
        monkeypatch.syspath_prepend(str(root))
        return root

    return _make
