import importlib.metadata
import re

import pytest

from sensorpipe.config import (
    dump_pipeline_config, load_pipeline_config, load_yaml, parse_pipeline_config, update_config_file,
)
from sensorpipe.errors import ConfigError

CONFIG = """\
# Boiler house: supply temperature loop
name: boiler-house  # do not rename, used by the historian
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
    options:
      interval: 300   # five-minute averages
      how: mean
  - kind: export
    options: {format: csv}
tags:
  area: north
"""


def test_ruamel_yaml_is_pinned_to_0_18_10():
    assert importlib.metadata.version("ruamel.yaml") == "0.18.10"


def test_load_pipeline_config(tmp_path):
    path = tmp_path / "pipeline.yaml"
    path.write_text(CONFIG)
    config = load_pipeline_config(path)
    assert config.name == "boiler-house"
    assert config.source.device_id == "TT-101" and config.source.timezone == "Europe/Berlin"
    assert [s.kind for s in config.stages] == ["convert", "resample", "export"]
    assert config.stages[1].options == {"interval": 300, "how": "mean"}
    assert config.tags == {"area": "north"}


def test_load_yaml_values_and_errors():
    data = load_yaml("a: [1, 2.5, true, null]\nb: {c: text}\n")
    assert data == {"a": [1, 2.5, True, None], "b": {"c": "text"}}
    assert load_yaml("") is None
    for broken in ["name: [unclosed", "a: b: c", "key: 'open"]:
        with pytest.raises(ConfigError):
            load_yaml(broken)


def test_dump_round_trip():
    config = parse_pipeline_config(load_yaml(CONFIG))
    text = dump_pipeline_config(config)
    assert isinstance(text, str) and "boiler-house" in text
    assert parse_pipeline_config(load_yaml(text)) == config


def test_update_keeps_comments_and_order(tmp_path):
    path = tmp_path / "pipeline.yaml"
    path.write_text(CONFIG)
    update_config_file(path, {"target_unit": "K", "tags": {"area": "south", "line": "4"}})
    text = path.read_text()
    assert text.startswith("# Boiler house: supply temperature loop\n")
    keys = [m.group(1) for m in re.finditer(r"^(\w+):", text, re.MULTILINE)]
    assert keys == ["name", "source", "target_unit", "stages", "tags"]
    config = load_pipeline_config(path)
    assert config.target_unit == "K" and config.tags == {"area": "south", "line": "4"}
    assert config.stages[1].options["interval"] == 300


def test_invalid_update_leaves_file_untouched(tmp_path):
    path = tmp_path / "pipeline.yaml"
    path.write_text(CONFIG)
    with pytest.raises(ConfigError):
        update_config_file(path, {"target_unit": "furlong"})
    assert path.read_text() == CONFIG
