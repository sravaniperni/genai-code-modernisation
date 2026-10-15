"""Validated job submissions and handler payload schemas (pydantic models)."""

from datetime import datetime, timezone
from typing import Any, Dict, Mapping, Optional, Type

from pydantic import BaseModel, Field, ValidationError, root_validator, validator

from jobqueue.errors import InvalidJobSpec
from jobqueue.job import Priority

QUEUE_NAME_PATTERN = r"^[a-z][a-z0-9_.-]{0,62}$"


class JobSpec(BaseModel):
    """An immutable, validated request to run handler ``name``; give ``delay`` (seconds) or ``run_at``."""

    name: str = Field(..., min_length=1, max_length=120)
    payload: Dict[str, Any] = Field(default_factory=dict)
    queue: str = Field("default", regex=QUEUE_NAME_PATTERN)
    priority: int = Field(int(Priority.NORMAL), ge=0, le=9)
    max_attempts: int = Field(3, ge=1, le=25)
    delay: float = Field(0.0, ge=0)
    run_at: Optional[datetime]
    unique_key: Optional[str] = Field(None, min_length=1, max_length=200)

    class Config:
        extra = "forbid"
        allow_mutation = False
        anystr_strip_whitespace = True

    @validator("run_at")
    def _require_aware(cls, value: Optional[datetime]) -> Optional[datetime]:
        if value is not None and value.tzinfo is None:
            raise ValueError("run_at must be timezone-aware")
        return value.astimezone(timezone.utc) if value is not None else None

    @root_validator
    def _delay_or_run_at(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        if values.get("delay") and values.get("run_at") is not None:
            raise ValueError("specify either delay or run_at, not both")
        return values


class PayloadSchema(BaseModel):
    """Base class for handler payload schemas; unknown keys are rejected."""

    class Config:
        extra = "forbid"


def _errors(exc: ValidationError, prefix: str = "") -> Dict[str, str]:
    out: Dict[str, str] = {}
    for error in exc.errors():
        location = ".".join([prefix] * bool(prefix) + [str(p) for p in error["loc"] if p != "__root__"])
        out.setdefault(location or "__root__", error["msg"])
    return out


def parse_spec(data: Mapping[str, Any]) -> JobSpec:
    """Validate a submission, raising :class:`InvalidJobSpec` with per-field messages."""
    try:
        return JobSpec.parse_obj(dict(data))
    except ValidationError as exc:
        raise InvalidJobSpec(_errors(exc)) from exc


def validate_payload(schema: Type[BaseModel], payload: Mapping[str, Any]) -> Dict[str, Any]:
    """Validate ``payload`` against a handler schema and return the normalised payload."""
    try:
        return schema.parse_obj(dict(payload)).dict()
    except ValidationError as exc:
        raise InvalidJobSpec(_errors(exc, "payload")) from exc
