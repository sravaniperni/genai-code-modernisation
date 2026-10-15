from pathlib import Path

import pytest

from sensorpipe.config import (
    Settings, dump_pipeline_config, load_pipeline_config, load_yaml, parse_pipeline_config, update_config_file,
)
from sensorpipe.errors import ConfigError

CONFIG = """\
# boiler house temperatures
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
    options: {format: csv}
"""


def test_load_pipeline_config(tmp_path):
    path = tmp_path / "pipeline.yaml"
    path.write_text(CONFIG)
    config = load_pipeline_config(path)
    assert config.name == "boiler-house"
    assert config.source.timezone == "Europe/Berlin" and config.source.format == "csv"
    assert [s.kind for s in config.stages] == ["convert", "resample", "export"]
    assert config.stages[1].options == {"interval": 300}


def test_invalid_configs():
    cases = [
        ({"stages": [{"kind": "explode"}]}, "kind"),
        ({"stages": [{"kind": "export"}, {"kind": "convert"}]}, "export"),
        ({"target_unit": "furlong"}, "target_unit"),
        ({"stages": []}, "stages"),
    ]
    for patch, message in cases:
        data = load_yaml(CONFIG)
        data.update(patch)
        with pytest.raises(ConfigError, match=message):
            parse_pipeline_config(data)


def test_invalid_yaml_and_shape():
    with pytest.raises(ConfigError):
        load_yaml("name: [unclosed")
    with pytest.raises(ConfigError):
        parse_pipeline_config(["not", "a", "mapping"])


def test_dump_round_trip():
    config = parse_pipeline_config(load_yaml(CONFIG))
    assert parse_pipeline_config(load_yaml(dump_pipeline_config(config))) == config


def test_update_config_file_keeps_comments(tmp_path):
    path = tmp_path / "pipeline.yaml"
    path.write_text(CONFIG)
    update_config_file(path, {"target_unit": "K"})
    text = path.read_text()
    assert text.startswith("# boiler house temperatures")
    assert load_pipeline_config(path).target_unit == "K"


def test_settings_from_environment(monkeypatch):
    monkeypatch.setenv("SENSORPIPE_ZSCORE_THRESHOLD", "2.5")
    settings = Settings()
    assert settings.zscore_threshold == 2.5
    assert settings.cache_dir == Path(".sensorpipe/cache")
