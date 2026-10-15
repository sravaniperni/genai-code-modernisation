from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest

from webhookrelay.clock import FixedClock
from webhookrelay.transports import HttpxTransport

T0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
SOURCE_SECRET = "src-secret-7f3a9c1e5b2d8f4a6c0e9b1d3f5a7c9e"
TARGET_SECRET = "tgt-secret-0b9d8c7e6f5a4b3c2d1e0f9a8b7c6d5e"


class Recorder:
    """httpx MockTransport handler that records requests and replays canned responses."""

    def __init__(self, *responses: httpx.Response):
        self.requests: list[httpx.Request] = []
        self.responses = list(responses)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        request.read()
        self.requests.append(request)
        if self.responses:
            return self.responses.pop(0)
        return httpx.Response(200, json={"ok": True})


def make_config(**overrides) -> dict:
    config = {
        "sources": {
            "acme": {"secret": SOURCE_SECRET},
            "plain": {},
        },
        "targets": {
            "audit": {"url": "https://audit.example/hooks?team=core", "secret": TARGET_SECRET},
            "chat": {"url": "https://chat.example/notify", "template": "chat.txt"},
        },
        "rules": [
            {"name": "orders", "events": ["order.*"], "targets": ["audit", "chat"], "priority": 10},
            {"name": "everything", "targets": ["audit"], "priority": 0},
        ],
        "retry": {"max_attempts": 3, "base_delay": 2, "factor": 2, "max_delay": 60},
        "base_url": "https://relay.example",
    }
    config.update(overrides)
    return config


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(T0)


@pytest.fixture
def recorder() -> Recorder:
    return Recorder()


@pytest.fixture
def transport(recorder: Recorder) -> HttpxTransport:
    return HttpxTransport(transport=httpx.MockTransport(recorder))
