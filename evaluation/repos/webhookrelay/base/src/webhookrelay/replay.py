"""Replaying archived webhook requests into a relay application.

Used to recover from downstream outages and to reproduce production traffic locally. An archive is a
JSON-lines file; each line holds ``source``, ``headers`` and either ``body`` (text) or ``body_b64``.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

import httpx

HOP_BY_HOP = frozenset({"host", "content-length", "transfer-encoding", "connection"})


@dataclass
class ArchivedRequest:
    source: str
    body: bytes
    headers: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_json(cls, line: str) -> ArchivedRequest:
        record = json.loads(line)
        if "body_b64" in record:
            body = base64.b64decode(record["body_b64"])
        else:
            body = str(record.get("body", "")).encode("utf-8")
        return cls(record["source"], body, dict(record.get("headers") or {}))


@dataclass
class ReplayResult:
    source: str
    status: int
    event_id: str | None
    deliveries: int


def load_archive(lines: Iterable[str]) -> list[ArchivedRequest]:
    """Parse archive lines, skipping blank lines and ``#`` comments."""
    return [ArchivedRequest.from_json(line) for line in lines if line.strip() and not line.lstrip().startswith("#")]


def replay(app: Any, requests: Iterable[ArchivedRequest], *, base_url: str = "http://relay") -> list[ReplayResult]:
    """POST each archived request to ``/hooks/<source>`` of the WSGI ``app`` in-process."""
    results: list[ReplayResult] = []
    with httpx.Client(app=app, base_url=base_url) as client:
        for item in requests:
            headers = {k: v for k, v in item.headers.items() if k.lower() not in HOP_BY_HOP}
            response = client.post(f"/hooks/{item.source}", content=item.body, headers=headers)
            is_json = response.headers.get("content-type", "").startswith("application/json")
            payload = response.json() if is_json else {}
            deliveries = len(payload.get("deliveries", []))
            results.append(ReplayResult(item.source, response.status_code, payload.get("event"), deliveries))
    return results
