"""Delivering routed events to their targets: rendering, signing, sending, retrying and record keeping."""

from __future__ import annotations

import hashlib
import json
import logging
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from werkzeug.urls import url_encode, url_parse

from .clock import SystemClock, isoformat_z, to_epoch
from .config import RelayConfig, Target
from .payloads import Event
from .routing import Router
from .scheduler import RetryScheduler, parse_retry_after
from .signatures import issue_delivery_token, sign_payload
from .transports import HttpxTransport, TransportError, TransportResponse, Urllib3Transport

log = logging.getLogger(__name__)


def build_delivery_url(base_url: str, params: Mapping[str, Any]) -> str:
    """Append ``params`` to the query string of ``base_url``.

    Existing query parameters and any fragment are kept. Parameters whose value is ``None`` are left
    out. Keys and values are form-encoded so the receiver decodes exactly the values given here.
    """
    url = url_parse(base_url)
    query = "&".join(part for part in (url.query, url_encode(params)) if part)
    return url.replace(query=query).to_url()


def delivery_id(event: Event, target: str) -> str:
    """Stable id for delivering ``event`` to ``target`` (the same across retries and replays)."""
    return hashlib.sha256(f"{event.source}:{event.id}:{target}".encode()).hexdigest()[:20]


@dataclass
class Delivery:
    id: str
    event: Event
    target: Target
    attempt: int = 0


@dataclass
class AttemptRecord:
    delivery_id: str
    target: str
    event_id: str
    attempt: int
    attempted_at: datetime
    status: int | None
    error: str | None = None
    next_retry_at: datetime | None = None

    @property
    def ok(self) -> bool:
        return self.status is not None and 200 <= self.status < 300

    def to_dict(self) -> dict[str, Any]:
        return {
            "delivery": self.delivery_id, "target": self.target, "event": self.event_id, "attempt": self.attempt,
            "status": self.status, "ok": self.ok, "error": self.error,
            "attempted_at": isoformat_z(self.attempted_at), "next_retry_at": isoformat_z(self.next_retry_at),
        }


class Dispatcher:
    """Routes events to targets and delivers them, scheduling retries for failed attempts."""

    def __init__(self, config: RelayConfig, *, transport: Any = None, clock: Any = None, renderer: Any = None):
        self.config = config
        self.clock = clock or SystemClock()
        self.router = Router(config.rules)
        self.scheduler = RetryScheduler(self.deliver, clock=self.clock)
        self.attempts: deque[AttemptRecord] = deque(maxlen=500)
        self._transport = transport
        self._transports: dict[str, Any] = {}
        self._renderer = renderer

    def transport_for(self, target: Target) -> Any:
        if self._transport is not None:
            return self._transport
        if target.transport not in self._transports:
            if target.transport == "pool":
                self._transports[target.transport] = Urllib3Transport()
            else:
                self._transports[target.transport] = HttpxTransport(proxy=self.config.proxy)
        return self._transports[target.transport]

    @property
    def renderer(self) -> Any:
        if self._renderer is None:  # imported lazily: only needed when a target uses a template
            from .templating import TemplateRenderer

            self._renderer = TemplateRenderer(base_url=self.config.base_url)
        return self._renderer

    def dispatch(self, event: Event) -> list[AttemptRecord]:
        names = self.router.route(event)
        if not names:
            log.warning("no route for %s event %s from %s", event.type, event.id, event.source)
            return []
        targets = [self.config.targets[name] for name in names]
        return [self.deliver(Delivery(delivery_id(event, t.name), event, t)) for t in targets]

    def render(self, delivery: Delivery) -> tuple[bytes, str]:
        template = delivery.target.template
        if not template:
            return json.dumps(delivery.event.to_dict(), sort_keys=True).encode(), "application/json"
        text = self.renderer.render(template, delivery.event)
        subtype = "html" if template.endswith(".html") else "plain"
        return text.encode("utf-8"), f"text/{subtype}; charset=utf-8"

    def headers_for(self, delivery: Delivery, body: bytes, content_type: str, now: datetime) -> dict[str, str]:
        target = delivery.target
        timestamp = to_epoch(now)
        headers = {
            "Content-Type": content_type,
            "X-Relay-Delivery": delivery.id,
            "X-Relay-Event": delivery.event.type,
            "X-Relay-Attempt": str(delivery.attempt),
            "X-Relay-Timestamp": str(timestamp),
        }
        if target.auth == "hmac":
            headers["X-Relay-Signature"] = sign_payload(target.secret or "", body, timestamp)
        elif target.auth == "jwt":
            token = issue_delivery_token(target.secret or "", issuer="webhookrelay", audience=target.name,
                                         subject=delivery.id, issued_at=now)
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def deliver(self, delivery: Delivery) -> AttemptRecord:
        """Make one delivery attempt; on failure, log it and schedule a retry if the policy allows."""
        target = delivery.target
        delivery.attempt += 1
        now = self.clock.now()
        body, content_type = self.render(delivery)
        url = build_delivery_url(target.url, {**target.params, "delivery": delivery.id})
        response: TransportResponse | None = None
        error: str | None = None
        try:
            headers = self.headers_for(delivery, body, content_type, now)
            response = self.transport_for(target).send("POST", url, body=body, headers=headers)
        except TransportError as exc:
            error = str(exc)
        status = response.status if response is not None else None
        record = AttemptRecord(delivery.id, target.name, delivery.event.id, delivery.attempt, now, status, error)
        if not record.ok:
            attempt, reason = delivery.attempt, error or f"HTTP {status}"
            log.warning("delivery %s to %s failed (attempt %d): %s", delivery.id, target.name, attempt, reason)
            policy = self.config.retry_policy_for(target)
            if policy.should_retry(attempt, status):
                retry_after = parse_retry_after(response.headers.get("retry-after"), now) if response else None
                record.next_retry_at = retry_after or now + timedelta(seconds=policy.delay_for(attempt))
                self.scheduler.schedule(delivery, record.next_retry_at)
            else:
                log.error("giving up on delivery %s to %s after %d attempt(s)", delivery.id, target.name, attempt)
        self.attempts.append(record)
        return record

    def stats(self) -> list[dict[str, Any]]:
        """Per-target counters for the status page."""
        empty = {"delivered": 0, "failed": 0, "last_status": None, "last_error": None, "last_attempt_at": None}
        rows = {name: {"name": name, **empty} for name in self.config.targets}
        for record in self.attempts:
            row = rows.setdefault(record.target, {"name": record.target, **empty})
            row["delivered" if record.ok else "failed"] += 1
            row.update(last_status=record.status, last_error=record.error, last_attempt_at=record.attempted_at)
        return list(rows.values())
