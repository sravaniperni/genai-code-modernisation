"""Scenario metadata for the recovery and security suites (collected by tests/conftest.py)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def scenario(sid: str, area: str, description: str) -> Callable[[Any], Any]:
    def mark(fn: Any) -> Any:
        fn._scenario = {"id": sid, "area": area, "description": description}
        return fn

    return mark
