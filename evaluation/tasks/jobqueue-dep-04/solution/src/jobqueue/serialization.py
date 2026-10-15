"""JSON export and import of jobs (marshmallow schemas)."""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any

from marshmallow import EXCLUDE, Schema, ValidationError, fields, post_dump, post_load, pre_load, validate, validates

from jobqueue.errors import SerializationError
from jobqueue.job import Job, JobState, Priority

EXPORT_VERSION = 1


class UTCDateTime(fields.Field):
    """ISO-8601 timestamps: written in UTC, naive input is read as UTC."""

    def _serialize(self, value: datetime | None, attr: str | None, obj: Any, **kwargs: Any) -> str | None:
        return value.astimezone(timezone.utc).isoformat() if value is not None else None

    def _deserialize(self, value: Any, attr: str | None, data: Any, **kwargs: Any) -> datetime:
        try:
            parsed = datetime.fromisoformat(value)
        except (TypeError, ValueError) as exc:
            raise ValidationError("Not a valid ISO-8601 datetime.") from exc
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


class JobRecordSchema(Schema):
    """One exported job. ``JobRecordSchema(redact_payload=True)`` masks payload values when dumping."""

    class Meta:
        unknown = EXCLUDE

    def __init__(self, *args: Any, redact_payload: bool = False, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.redact_payload = redact_payload

    id = fields.Str(required=True)
    name = fields.Str(required=True)
    queue = fields.Str(load_default="default")
    state = fields.Str(load_default=JobState.PENDING.value, validate=validate.OneOf([s.value for s in JobState]))
    priority = fields.Int(load_default=int(Priority.NORMAL), validate=validate.Range(0, 9))
    payload = fields.Dict(keys=fields.Str(), load_default=dict)
    attempts = fields.Int(load_default=0, validate=validate.Range(min=0))
    max_attempts = fields.Int(load_default=3, validate=validate.Range(min=1))
    run_at = UTCDateTime(allow_none=True, load_default=None)
    created_at = UTCDateTime(required=True)
    finished_at = UTCDateTime(allow_none=True, load_default=None)
    last_error = fields.Str(allow_none=True, load_default=None)
    unique_key = fields.Str(allow_none=True, load_default=None)

    @validates("name")
    def _validate_name(self, value: str, **kwargs: Any) -> None:
        if not value.strip():
            raise ValidationError("Handler name must not be blank.")

    @pre_load(pass_collection=True)
    def _unwrap(self, data: Any, many: bool, **kwargs: Any) -> Any:
        if many and isinstance(data, dict) and "jobs" in data:
            if data.get("version", EXPORT_VERSION) != EXPORT_VERSION:
                raise ValidationError(f"unsupported export version {data.get('version')!r}", "version")
            return data["jobs"]
        return data

    @post_dump
    def _redact(self, data: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        if self.redact_payload:
            data["payload"] = {key: "***" for key in data["payload"]}
        return data

    @post_load
    def _make_job(self, data: dict[str, Any], **kwargs: Any) -> Job:
        return Job(**{**data, "state": JobState(data["state"])})


def dump_jobs(jobs: Iterable[Job], *, redact_payload: bool = False) -> str:
    """Serialise ``jobs`` to the export format (a JSON document)."""
    schema = JobRecordSchema(many=True, redact_payload=redact_payload)
    return json.dumps({"version": EXPORT_VERSION, "jobs": schema.dump(list(jobs))}, indent=2, sort_keys=True)


def load_jobs(text: str) -> list[Job]:
    """Parse an export (or a bare JSON list of job records); raises :class:`SerializationError`."""
    try:
        return JobRecordSchema(many=True).load(json.loads(text))
    except ValueError as exc:  # json.JSONDecodeError
        raise SerializationError({"_schema": [f"not valid JSON: {exc}"]}) from exc
    except ValidationError as exc:
        raise SerializationError(exc.messages) from exc
