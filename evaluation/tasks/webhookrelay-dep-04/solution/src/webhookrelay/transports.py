"""Outbound HTTP transports.

Both transports accept an injectable lower layer (an httpx transport, a urllib3 pool), so tests and dry
runs never open network connections.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import httpx
import urllib3
from urllib3.util.retry import Retry

USER_AGENT = "webhookrelay/1.4"
POOL_RETRY_STATUSES = (429, 502, 503, 504)


class TransportError(Exception):
    """The request could not be completed (connection failure, timeout, too many retries)."""


@dataclass
class TransportResponse:
    status: int
    headers: dict[str, str] = field(default_factory=dict)  # lower-cased header names
    body: str = ""

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300


class HttpxTransport:
    """Default transport: one pooled ``httpx.Client``, optionally through an outbound proxy."""

    def __init__(
        self, *, timeout: float = 10.0, proxy: str | None = None, transport: httpx.BaseTransport | None = None
    ):
        self.client = httpx.Client(
            timeout=timeout, proxies=proxy, transport=transport, headers={"User-Agent": USER_AGENT}
        )

    def send(self, method: str, url: str, *, body: bytes, headers: Mapping[str, str]) -> TransportResponse:
        try:
            response = self.client.request(method, url, content=body, headers=dict(headers))
        except httpx.HTTPError as exc:
            raise TransportError(f"{type(exc).__name__}: {exc}") from exc
        return TransportResponse(
            response.status_code, {k.lower(): v for k, v in response.headers.items()}, response.text
        )

    def close(self) -> None:
        self.client.close()


class PoolRetry(Retry):
    """urllib3 retry policy for the pooled transport, with a 30 second backoff cap instead of urllib3's 120."""

    DEFAULT_BACKOFF_MAX = 30


def build_pool_retry(total: int = 3, backoff_factor: float = 0.5) -> Retry:
    """Retry transient failures inside the pool. Deliveries carry a delivery id, so POST is safe to retry."""
    return PoolRetry(
        total=total,
        backoff_factor=backoff_factor,
        backoff_max=PoolRetry.DEFAULT_BACKOFF_MAX,
        status_forcelist=POOL_RETRY_STATUSES,
        allowed_methods=Retry.DEFAULT_ALLOWED_METHODS | {"POST"},
        raise_on_status=False,
    )


class Urllib3Transport:
    """Transport for high-volume targets: a shared urllib3 pool that retries transient failures itself."""

    def __init__(self, *, retries: int = 3, backoff_factor: float = 0.5, timeout: float = 10.0, pool: Any = None):
        self.retry = build_pool_retry(retries, backoff_factor)
        self.timeout = urllib3.Timeout(connect=timeout, read=timeout)
        self.pool = pool if pool is not None else urllib3.PoolManager(num_pools=8)

    def send(self, method: str, url: str, *, body: bytes, headers: Mapping[str, str]) -> TransportResponse:
        try:
            response = self.pool.urlopen(
                method, url, body=body, headers={"User-Agent": USER_AGENT, **headers},
                retries=self.retry, timeout=self.timeout, redirect=False, preload_content=True,
            )
        except urllib3.exceptions.HTTPError as exc:
            raise TransportError(f"{type(exc).__name__}: {exc}") from exc
        headers_out = {k.lower(): v for k, v in response.headers.items()}
        return TransportResponse(response.status, headers_out, response.data.decode("utf-8", "replace"))

    def close(self) -> None:
        if hasattr(self.pool, "clear"):
            self.pool.clear()
