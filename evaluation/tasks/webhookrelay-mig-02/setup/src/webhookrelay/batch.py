"""Concurrent batch sends (backfills, bulk re-deliveries) on ``httpx.AsyncClient``."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, field

import httpx


@dataclass
class BatchRequest:
    url: str
    body: bytes
    headers: dict[str, str] = field(default_factory=dict)


@dataclass
class BatchResult:
    url: str
    status: int | None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.status is not None and 200 <= self.status < 300


class BatchSender:
    """Sends many requests with at most ``concurrency`` in flight at a time."""

    def __init__(self, *, concurrency: int = 8, timeout: float = 10.0, proxy: str | None = None,
                 transport: httpx.AsyncBaseTransport | None = None):
        if concurrency < 1:
            raise ValueError("concurrency must be at least 1")
        self.concurrency = concurrency
        self.timeout = timeout
        self.proxy = proxy
        self.transport = transport

    async def send_batch(self, requests: Sequence[BatchRequest]) -> list[BatchResult]:
        """Send every request; the results are in the same order as ``requests``."""
        semaphore = asyncio.Semaphore(self.concurrency)
        async with httpx.AsyncClient(timeout=self.timeout, proxies=self.proxy, transport=self.transport) as client:

            async def send_one(item: BatchRequest) -> BatchResult:
                async with semaphore:
                    try:
                        response = await client.post(item.url, content=item.body, headers=item.headers)
                    except httpx.HTTPError as exc:
                        return BatchResult(item.url, None, f"{type(exc).__name__}: {exc}")
                    return BatchResult(item.url, response.status_code)

            return list(await asyncio.gather(*(send_one(item) for item in requests)))

    def send_all(self, requests: Sequence[BatchRequest]) -> list[BatchResult]:
        """Blocking entry point for scripts and the command line."""
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(self.send_batch(requests))
