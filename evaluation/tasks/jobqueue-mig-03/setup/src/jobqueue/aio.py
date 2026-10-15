"""Support for ``async def`` handlers."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable, Coroutine
from typing import Any


def run_coroutine(coro: Coroutine[Any, Any, Any]) -> Any:
    """Run ``coro`` to completion from synchronous code (a worker thread or the main thread)."""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:  # worker threads have no event loop until we create one
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    if loop.is_running():
        coro.close()
        raise RuntimeError("run_coroutine() cannot be used inside a running event loop; await the coroutine")
    return loop.run_until_complete(coro)


def run_handler(func: Callable[[dict[str, Any]], Any], payload: dict[str, Any]) -> Any:
    """Call a handler; a coroutine handler is run to completion and its result returned."""
    result = func(payload)
    return run_coroutine(result) if inspect.iscoroutine(result) else result
