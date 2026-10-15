"""Structured JSON logging with credential redaction.

All log records are emitted as one JSON object per line. Before serialisation every string is passed
through :func:`redact`, which masks configured secret values and common credential formats so that a
token can never reach stdout, log files, or the task event stream.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import UTC, datetime
from typing import Any

_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"sk-(?:ant-)?[A-Za-z0-9_\-]{16,}"),
    re.compile(r"(?i)(authorization\s*[:=]\s*)(bearer|token|basic)\s+[A-Za-z0-9._\-+/=]+"),
    re.compile(r"(?i)(x-access-token:)[^@\s]+"),
    re.compile(r"(?i)(https?://)[^/\s:@]+:[^/\s@]+@"),
]

_known_secrets: set[str] = set()

REDACTED = "[REDACTED]"


def register_secret(value: str | None) -> None:
    if value and len(value) >= 6:
        _known_secrets.add(value)


def redact(text: str) -> str:
    if not text:
        return text
    for secret in _known_secrets:
        if secret in text:
            text = text.replace(secret, REDACTED)
    for pattern in _PATTERNS:
        if pattern.groups:
            text = pattern.sub(lambda m: (m.group(1) or "") + REDACTED, text)
        else:
            text = pattern.sub(REDACTED, text)
    return text


def redact_obj(value: Any) -> Any:
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {k: redact_obj(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [redact_obj(v) for v in value]
    return value


_RESERVED = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(redact_obj(payload), default=str)


def configure_logging(level: str = "INFO", secrets: list[str] | None = None) -> None:
    for secret in secrets or []:
        register_secret(secret)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
    for noisy in ("httpx", "httpcore", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
