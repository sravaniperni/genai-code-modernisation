"""Canonical payload encoding and size limits."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import date
from typing import Any

from jobqueue.errors import InvalidJobSpec, PayloadTooLarge

DEFAULT_MAX_PAYLOAD_BYTES = 64 * 1024


def _default(value: Any) -> Any:
    if not isinstance(value, date):
        raise TypeError(f"{type(value).__name__} is not JSON serialisable")
    return value.isoformat()


def encode_payload(payload: Mapping[str, Any]) -> str:
    """Encode ``payload`` as compact, key-sorted JSON text; this is what the stores persist."""
    try:
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=_default)
    except (TypeError, ValueError) as exc:
        raise InvalidJobSpec({"payload": str(exc)}) from exc


def decode_payload(text: str | None) -> dict[str, Any]:
    return json.loads(text) if text else {}


def payload_size(payload: Mapping[str, Any]) -> int:
    """Size of the stored payload."""
    return len(encode_payload(payload))


def check_payload_size(payload: Mapping[str, Any], limit: int = DEFAULT_MAX_PAYLOAD_BYTES) -> int:
    """Return the payload size, raising :class:`PayloadTooLarge` when it exceeds ``limit`` bytes."""
    size = payload_size(payload)
    if size > limit:
        raise PayloadTooLarge(size, limit)
    return size
