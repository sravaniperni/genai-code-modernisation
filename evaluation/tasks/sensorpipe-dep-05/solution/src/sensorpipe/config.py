"""Pipeline configuration: YAML documents validated with pydantic models, plus runtime settings."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Dict, List, Optional

import ruamel.yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from sensorpipe.errors import ConfigError
from sensorpipe.timeutil import get_zone
from sensorpipe.units import get_unit


class SourceConfig(BaseModel):
    model_config = ConfigDict(coerce_numbers_to_str=True)

    path: str
    format: str = Field("csv", pattern=r"^(csv|json)$")
    device_id: Optional[str] = None
    channel: Optional[str] = None
    unit: Optional[str] = None
    timezone: str = "UTC"
    timestamp_format: Optional[str] = None

    @field_validator("timezone")
    @classmethod
    def _known_zone(cls, value: str) -> str:
        get_zone(value)
        return value


class StageConfig(BaseModel):
    kind: str = Field(..., pattern=r"^(convert|calibrate|resample|detect|export)$")
    options: Dict[str, Any] = {}


class PipelineConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", coerce_numbers_to_str=True)

    name: str
    source: SourceConfig
    stages: List[StageConfig] = Field(..., min_length=1)
    target_unit: Optional[str] = None
    tags: Dict[str, str] = {}

    @field_validator("target_unit")
    @classmethod
    def _known_unit(cls, value: Optional[str]) -> Optional[str]:
        if value is not None:
            get_unit(value)
        return value

    @model_validator(mode="after")
    def _export_is_last(self) -> "PipelineConfig":
        kinds = [stage.kind for stage in self.stages]
        if "export" in kinds and kinds[-1] != "export":
            raise ValueError("the export stage must be the last stage")
        return self


class Settings(BaseSettings):
    """Runtime settings, overridable with ``SENSORPIPE_*`` environment variables."""

    model_config = SettingsConfigDict(env_prefix="SENSORPIPE_")

    cache_dir: Path = Path(".sensorpipe/cache")
    buffer_path: Path = Path(".sensorpipe/buffer.sqlite3")
    default_timezone: str = "UTC"
    zscore_threshold: float = 3.0


def load_yaml(text: str) -> Any:
    try:
        return ruamel.yaml.safe_load(text)
    except ruamel.yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML: {exc}") from exc


def parse_pipeline_config(data: Any) -> PipelineConfig:
    if not isinstance(data, Mapping):
        raise ConfigError("a pipeline configuration must be a mapping")
    try:
        return PipelineConfig.model_validate(dict(data))
    except ValidationError as exc:
        problems = "; ".join(f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in exc.errors())
        raise ConfigError(f"invalid pipeline configuration: {problems}") from exc


def load_pipeline_config(path: str | Path) -> PipelineConfig:
    return parse_pipeline_config(load_yaml(Path(path).read_text(encoding="utf-8")))


def dump_pipeline_config(config: PipelineConfig) -> str:
    return ruamel.yaml.round_trip_dump(config.model_dump(exclude_none=True), default_flow_style=False)


def update_config_file(path: str | Path, updates: Mapping[str, Any]) -> None:
    """Set top-level keys of a pipeline YAML file in place, keeping comments and key order."""
    path = Path(path)
    data = ruamel.yaml.round_trip_load(path.read_text(encoding="utf-8"))
    for key, value in updates.items():
        data[key] = value
    parse_pipeline_config(data)
    path.write_text(ruamel.yaml.round_trip_dump(data), encoding="utf-8")

