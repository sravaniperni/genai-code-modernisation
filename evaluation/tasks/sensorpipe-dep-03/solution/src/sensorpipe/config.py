"""Pipeline configuration: YAML documents validated with pydantic models, plus runtime settings."""

from __future__ import annotations

from collections.abc import Mapping
from io import StringIO
from pathlib import Path
from typing import Any, Dict, List, Optional

from ruamel.yaml import YAML, YAMLError
from pydantic import BaseModel, BaseSettings, Field, ValidationError, root_validator, validator

from sensorpipe.errors import ConfigError
from sensorpipe.timeutil import get_zone
from sensorpipe.units import get_unit


class SourceConfig(BaseModel):
    path: str
    format: str = Field("csv", regex=r"^(csv|json)$")
    device_id: Optional[str]
    channel: Optional[str]
    unit: Optional[str]
    timezone: str = "UTC"
    timestamp_format: Optional[str]

    @validator("timezone")
    def _known_zone(cls, value: str) -> str:
        get_zone(value)
        return value


class StageConfig(BaseModel):
    kind: str = Field(..., regex=r"^(convert|calibrate|resample|detect|export)$")
    options: Dict[str, Any] = {}


class PipelineConfig(BaseModel):
    name: str
    source: SourceConfig
    stages: List[StageConfig] = Field(..., min_items=1)
    target_unit: Optional[str]
    tags: Dict[str, str] = {}

    class Config:
        allow_mutation = False
        extra = "forbid"

    @validator("target_unit")
    def _known_unit(cls, value: Optional[str]) -> Optional[str]:
        if value is not None:
            get_unit(value)
        return value

    @root_validator
    def _export_is_last(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        kinds = [stage.kind for stage in values.get("stages") or []]
        if "export" in kinds and kinds[-1] != "export":
            raise ValueError("the export stage must be the last stage")
        return values


class Settings(BaseSettings):
    """Runtime settings, overridable with ``SENSORPIPE_*`` environment variables."""

    cache_dir: Path = Path(".sensorpipe/cache")
    buffer_path: Path = Path(".sensorpipe/buffer.sqlite3")
    default_timezone: str = "UTC"
    zscore_threshold: float = 3.0

    class Config:
        env_prefix = "SENSORPIPE_"


def _dump_yaml(data: Any) -> str:
    """Serialise with the round-trip dumper (keeps comments and key order of loaded documents)."""
    yaml = YAML()
    yaml.default_flow_style = False
    stream = StringIO()
    yaml.dump(data, stream)
    return stream.getvalue()


def load_yaml(text: str) -> Any:
    try:
        return YAML(typ="safe", pure=True).load(text)
    except YAMLError as exc:
        raise ConfigError(f"invalid YAML: {exc}") from exc


def parse_pipeline_config(data: Any) -> PipelineConfig:
    if not isinstance(data, Mapping):
        raise ConfigError("a pipeline configuration must be a mapping")
    try:
        return PipelineConfig.parse_obj(dict(data))
    except ValidationError as exc:
        problems = "; ".join(f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in exc.errors())
        raise ConfigError(f"invalid pipeline configuration: {problems}") from exc


def load_pipeline_config(path: str | Path) -> PipelineConfig:
    return parse_pipeline_config(load_yaml(Path(path).read_text(encoding="utf-8")))


def dump_pipeline_config(config: PipelineConfig) -> str:
    return _dump_yaml(config.dict(exclude_none=True))


def update_config_file(path: str | Path, updates: Mapping[str, Any]) -> None:
    """Set top-level keys of a pipeline YAML file in place, keeping comments and key order."""
    path = Path(path)
    data = YAML().load(path.read_text(encoding="utf-8"))
    for key, value in updates.items():
        data[key] = value
    parse_pipeline_config(data)
    path.write_text(_dump_yaml(data), encoding="utf-8")

