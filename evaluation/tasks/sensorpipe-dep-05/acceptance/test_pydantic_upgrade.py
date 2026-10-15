import importlib.metadata
from pathlib import Path

import pytest

from sensorpipe.config import (
    Settings, dump_pipeline_config, load_pipeline_config, load_yaml, parse_pipeline_config,
)
from sensorpipe.errors import ConfigError

CONFIG = """\
name: boiler-house
source:
  path: readings.csv
  device_id: TT-101
  channel: temp
  unit: degF
  timezone: Europe/Berlin
target_unit: degC
stages:
  - kind: convert
  - kind: resample
    options: {interval: 300}
  - kind: export
tags:
  area: north
"""


def data(**patch):
    loaded = load_yaml(CONFIG)
    loaded.update(patch)
    return loaded


def test_pydantic_is_pinned_to_2_10_6():
    assert importlib.metadata.version("pydantic") == "2.10.6"


def test_full_config(tmp_path):
    path = tmp_path / "pipeline.yaml"
    path.write_text(CONFIG)
    config = load_pipeline_config(path)
    assert config.name == "boiler-house" and config.target_unit == "degC"
    assert config.source.format == "csv" and config.source.timestamp_format is None
    assert [s.kind for s in config.stages] == ["convert", "resample", "export"]
    assert config.stages[0].options == {} and config.stages[1].options == {"interval": 300}


def test_optional_fields_may_be_omitted():
    config = parse_pipeline_config({"name": "minimal", "source": {"path": "in.json", "format": "json"},
                                    "stages": [{"kind": "export"}]})
    assert config.target_unit is None and config.tags == {}
    assert config.source.device_id is None and config.source.channel is None and config.source.unit is None
    assert config.source.timezone == "UTC"


def test_numeric_values_are_read_as_strings():
    source = {"path": "in.csv", "device_id": 1042, "channel": "temp", "unit": "degC"}
    config = parse_pipeline_config(data(source=source, tags={"line": 4, "area": "north"}))
    assert config.source.device_id == "1042"
    assert config.tags == {"line": "4", "area": "north"}


@pytest.mark.parametrize("patch, field", [
    ({"stages": [{"kind": "explode"}]}, "kind"),
    ({"stages": []}, "stages"),
    ({"target_unit": "furlong"}, "target_unit"),
    ({"source": {"path": "x.csv", "timezone": "Mars/Base"}}, "timezone"),
    ({"source": {"path": "x.xml", "format": "xml"}}, "format"),
    ({"name": None}, "name"),
    ({"stages": [{"kind": "export"}, {"kind": "convert"}]}, "export stage must be the last"),
])
def test_invalid_configs_name_the_field(patch, field):
    with pytest.raises(ConfigError, match=field):
        parse_pipeline_config(data(**patch))


def test_unknown_top_level_keys_are_rejected():
    with pytest.raises(ConfigError, match="schedule"):
        parse_pipeline_config(data(schedule="hourly"))


def test_configs_are_immutable():
    config = parse_pipeline_config(data())
    with pytest.raises((TypeError, ValueError)):
        config.name = "renamed"
    assert config.name == "boiler-house"


def test_dump_round_trip():
    config = parse_pipeline_config(data())
    assert parse_pipeline_config(load_yaml(dump_pipeline_config(config))) == config


def test_settings_defaults_and_environment(monkeypatch):
    settings = Settings()
    assert settings.cache_dir == Path(".sensorpipe/cache") and settings.zscore_threshold == 3.0
    monkeypatch.setenv("SENSORPIPE_ZSCORE_THRESHOLD", "2.5")
    monkeypatch.setenv("SENSORPIPE_CACHE_DIR", "/var/cache/sensorpipe")
    settings = Settings()
    assert settings.zscore_threshold == 2.5
    assert settings.cache_dir == Path("/var/cache/sensorpipe")
    assert Settings(default_timezone="Europe/Berlin").default_timezone == "Europe/Berlin"
