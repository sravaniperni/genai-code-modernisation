"""Support for ``async def`` handlers."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable, Coroutine
from typing import Any


def run_coroutine(coro: Coroutine[Any, Any, Any]) -> Any:
    """Run ``coro`` to completion from synchronous code (a worker thread or the main thread)."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        coro.close()
        raise RuntimeError("run_coroutine() cannot be used inside a running event loop; await the coroutine")
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()


def run_handler(func: Callable[[dict[str, Any]], Any], payload: dict[str, Any]) -> Any:
    """Call a handler; a coroutine handler is run to completion and its result returned."""
    result = func(payload)
    return run_coroutine(result) if inspect.iscoroutine(result) else result
