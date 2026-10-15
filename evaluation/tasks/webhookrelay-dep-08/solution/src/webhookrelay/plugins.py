"""Event plugins: objects with a ``name`` and ``transform(event)`` returning the event or ``None`` to drop it.

Third-party plugins are discovered through the ``webhookrelay.plugins`` entry-point group; an entry point
refers to a plugin class (instantiated without arguments) or to a ready plugin object.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import importlib_metadata

from .payloads import Event

PLUGIN_GROUP = "webhookrelay.plugins"
SECRET_KEYS = ("password", "secret", "token", "api_key", "apikey")


class PluginError(RuntimeError):
    """A plugin could not be found, loaded or registered."""


class RedactSecrets:
    """Blank out credential-looking values before an event leaves the relay."""

    name = "redact-secrets"

    def transform(self, event: Event) -> Event:
        event.data = _redact(event.data)
        return event


class DropPings:
    """Drop the connectivity checks some senders emit when a webhook is first configured."""

    name = "drop-pings"

    def transform(self, event: Event) -> Event | None:
        return None if event.type in ("ping", "zen") else event


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: "***" if any(s in str(k).lower() for s in SECRET_KEYS) else _redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


class PluginRegistry:
    def __init__(self) -> None:
        self._plugins: dict[str, Any] = {}
        self._origins: dict[str, str] = {}

    def register(self, plugin: Any, *, origin: str = "builtin") -> None:
        name = getattr(plugin, "name", None)
        if not isinstance(name, str) or not callable(getattr(plugin, "transform", None)):
            raise PluginError(f"{plugin!r} is not a plugin (needs a name and a transform method)")
        if name in self._plugins:
            raise PluginError(f"plugin {name!r} is already registered")
        self._plugins[name] = plugin
        self._origins[name] = origin

    def get(self, name: str) -> Any:
        try:
            return self._plugins[name]
        except KeyError:
            raise PluginError(f"no plugin named {name!r}") from None

    def names(self) -> list[str]:
        return list(self._plugins)

    def describe(self) -> list[dict[str, str]]:
        return [{"name": name, "origin": self._origins[name]} for name in self._plugins]

    def apply(self, event: Event) -> Event | None:
        """Run every plugin in registration order; stop as soon as one drops the event."""
        for plugin in self._plugins.values():
            event = plugin.transform(event)
            if event is None:
                return None
        return event

    @staticmethod
    def _instantiate(entry_point: Any) -> tuple[Any, str]:
        try:
            obj = entry_point.load()
        except Exception as exc:
            raise PluginError(f"cannot load plugin {entry_point.name!r}: {exc}") from exc
        plugin = obj() if isinstance(obj, type) else obj
        dist = getattr(entry_point, "dist", None)
        origin = f"{dist.name} {dist.version}" if dist is not None else "entry point"
        return plugin, origin

    def discover(self, enabled: Iterable[str] | None = None, group: str = PLUGIN_GROUP) -> list[str]:
        """Register plugins advertised by installed distributions; returns the names newly registered.

        ``enabled`` limits discovery to the given entry-point names (``None`` means all of them).
        """
        wanted = set(enabled) if enabled is not None else None
        loaded: list[str] = []
        entry_points = importlib_metadata.entry_points(group=group)
        for entry_point in sorted(entry_points, key=lambda ep: ep.name):
            if (wanted is not None and entry_point.name not in wanted) or entry_point.name in self._plugins:
                continue
            plugin, origin = self._instantiate(entry_point)
            self.register(plugin, origin=origin)
            loaded.append(plugin.name)
        return loaded

    def load(self, name: str, group: str = PLUGIN_GROUP) -> Any:
        """Load and register the single plugin published under entry-point name ``name``."""
        matches = list(importlib_metadata.entry_points(group=group, name=name))
        if not matches:
            raise PluginError(f"no entry point {name!r} in group {group!r}")
        plugin, origin = self._instantiate(matches[0])
        self.register(plugin, origin=origin)
        return plugin


def default_registry(enabled: Iterable[str] | None = None) -> PluginRegistry:
    """The built-in plugins, plus the third-party plugins named in ``enabled``."""
    registry = PluginRegistry()
    registry.register(DropPings())
    registry.register(RedactSecrets())
    if enabled:
        registry.discover(enabled)
    return registry
