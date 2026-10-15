"""Outbound completion webhooks (urllib3)."""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import urllib3
from urllib3.util.retry import Retry

from jobqueue.errors import WebhookError
from jobqueue.job import Job

RETRY_STATUSES = (429, 500, 502, 503, 504)


@dataclass(frozen=True)
class Delivery:
    status: int
    delivery_id: str | None


class WebhookNotifier:
    """POSTs a JSON event to ``url`` when a job reaches one of the ``events`` states.

    Connection errors and ``RETRY_STATUSES`` are retried with exponential backoff; ``http`` may be any
    object with the ``request()`` method of a urllib3 ``PoolManager``.
    """

    def __init__(self, url: str, *, secret: str | None = None, http: Any = None, retries: int = 3,
                 backoff_factor: float = 0.5, timeout: float = 10.0, events: Iterable[str] = ("succeeded", "failed")):
        self.url, self.secret, self.events = url, secret, frozenset(events)
        self.retry = Retry(total=retries, backoff_factor=backoff_factor, status_forcelist=RETRY_STATUSES,
                           method_whitelist=Retry.DEFAULT_METHOD_WHITELIST | {"POST"}, raise_on_status=False)
        self.timeout = urllib3.Timeout(connect=timeout, read=timeout)
        self.http = http if http is not None else urllib3.PoolManager()

    def build(self, job: Job) -> tuple[bytes, dict[str, str]]:
        event = f"job.{job.state.value}"
        body = json.dumps({"event": event, "job": job.summary()}, sort_keys=True).encode("utf-8")
        headers = {"Content-Type": "application/json", "X-Jobqueue-Event": event}
        if self.secret:
            digest = hmac.new(self.secret.encode(), body, hashlib.sha256).hexdigest()
            headers["X-Jobqueue-Signature"] = f"sha256={digest}"
        return body, headers

    def notify(self, job: Job) -> Delivery | None:
        """Deliver the event for ``job``; ``None`` if its state is not subscribed."""
        if job.state.value not in self.events:
            return None
        body, headers = self.build(job)
        try:
            response = self.http.request("POST", self.url, body=body, headers=headers, retries=self.retry,
                                         timeout=self.timeout)
        except urllib3.exceptions.HTTPError as exc:
            raise WebhookError(f"webhook delivery to {self.url} failed: {exc}") from exc
        received = response.getheaders()
        if response.status >= 400:
            raise WebhookError(f"webhook endpoint {self.url} answered HTTP {response.status}",
                               status=response.status, retry_after=self._retry_after(received.get("Retry-After")))
        return Delivery(response.status, received.get("X-Delivery-Id"))

    @staticmethod
    def _retry_after(value: str | None) -> float | None:
        """Seconds to wait before redelivering, capped at urllib3's maximum backoff."""
        try:
            return min(max(float(value), 0.0), Retry.BACKOFF_MAX) if value is not None else None
        except ValueError:
            return None
