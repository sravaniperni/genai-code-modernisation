import os
import re
from pathlib import Path

import pytest

from sensorpipe.calibration import CalibrationCurve, list_bundled_tables, load_bundled_table
from sensorpipe.errors import CalibrationError


def test_list_bundled_tables():
    assert list_bundled_tables() == ["ntc10k", "pt100", "type_k"]


@pytest.mark.parametrize("name, raw, expected", [
    ("pt100", 80.31, -50.0), ("pt100", 100.0, 0.0), ("pt100", 110.0, 25.773), ("pt100", 175.86, 200.0),
    ("type_k", 4.096, 100.0), ("type_k", 3.06, 75.0),
    ("ntc10k", 10.0, 25.0), ("ntc10k", 1.492, 75.0),
])
def test_table_values(name, raw, expected):
    curve = load_bundled_table(name)
    assert isinstance(curve, CalibrationCurve)
    assert curve.name == name and curve.unit == "degC"
    assert curve.apply(raw) == pytest.approx(expected, abs=0.05)


def test_table_ranges():
    assert load_bundled_table("pt100").range == (80.31, 212.05)
    assert load_bundled_table("type_k").range == (0.0, 12.209)
    assert len(load_bundled_table("ntc10k").raw) == 5


@pytest.mark.parametrize("name", ["pt9999", "PT100", "__init__", ""])
def test_unknown_tables(name):
    with pytest.raises(CalibrationError):
        load_bundled_table(name)


def test_legacy_resource_functions_are_gone():
    src = Path(os.environ.get("REPO_ROOT", ".")) / "src"
    legacy = r"(?:open_text|open_binary|read_text|read_binary|is_resource|contents|path)"
    patterns = [re.compile(rf"\bresources\.{legacy}\s*\("),
                re.compile(rf"from\s+importlib(?:_|\.)resources\s+import\s+[^\n]*\b{legacy}\b")]
    offenders = [f"{p.name}: {m.group(0)}" for p in src.rglob("*.py") for pattern in patterns
                 for m in pattern.finditer(p.read_text())]
    assert offenders == []
