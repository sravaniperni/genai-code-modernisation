"""Handler registration and plugin discovery."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from importlib_metadata import entry_points

from jobqueue.errors import HandlerNotFound

ENTRY_POINT_GROUP = "jobqueue.handlers"
Handler = Callable[[dict[str, Any]], Any]
log = logging.getLogger("jobqueue.registry")


@dataclass(frozen=True)
class HandlerInfo:
    name: str
    func: Handler
    schema: type | None = None
    origin: str = "local"


class HandlerRegistry:
    """Maps job names to handler callables (plain functions or ``async def`` coroutines)."""

    def __init__(self) -> None:
        self._handlers: dict[str, HandlerInfo] = {}

    def register(self, name: str, func: Handler | None = None, *, schema: type | None = None,
                 replace: bool = False) -> Any:
        """Register ``func`` under ``name``; without ``func`` this returns a decorator."""

        def decorator(target: Handler) -> Handler:
            if name in self._handlers and not replace:
                raise ValueError(f"handler {name!r} is already registered")
            self._handlers[name] = HandlerInfo(name, target, schema)
            return target

        return decorator(func) if func is not None else decorator

    def get(self, name: str) -> HandlerInfo:
        if name not in self._handlers:
            raise HandlerNotFound(f"no handler registered for {name!r}")
        return self._handlers[name]

    def discover(self, group: str = ENTRY_POINT_GROUP) -> list[str]:
        """Register the handlers installed distributions advertise in entry-point ``group``; returns new names.

        A plugin handler may carry a ``payload_schema`` attribute. Local registrations win over plugins.
        """
        added = []
        for entry_point in entry_points(group=group):
            dist = getattr(entry_point, "dist", None)
            origin = f"plugin:{dist.name}=={dist.version}" if dist is not None else "plugin"
            if entry_point.name in self._handlers:
                log.info("handler %r from %s ignored: name already registered", entry_point.name, origin)
                continue
            target = entry_point.load()
            schema = getattr(target, "payload_schema", None)
            self._handlers[entry_point.name] = HandlerInfo(entry_point.name, target, schema, origin)
            added.append(entry_point.name)
        return sorted(added)
