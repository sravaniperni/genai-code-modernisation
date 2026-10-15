"""Publisher plugin system.

Besides the built-in publishers, installed distributions can register :class:`Publisher` subclasses
under the ``releasebot.publishers`` entry-point group (``slack = "releasebot_slack:SlackPublisher"``).
"""

from __future__ import annotations

import logging
import pkgutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

import importlib_metadata

from releasebot.errors import PluginError

if TYPE_CHECKING:
    from releasebot.config import ProjectConfig
    from releasebot.release import ReleasePlan

ENTRY_POINT_GROUP = "releasebot.publishers"
BUILTIN_ORIGIN = "releasebot (built-in)"
log = logging.getLogger(__name__)


def module_available(name: str) -> bool:
    """True if module ``name`` could be imported; the module itself is not imported."""
    try:
        return pkgutil.find_loader(name) is not None
    except ImportError:
        return False


@dataclass
class PublishContext:
    workdir: Path
    dry_run: bool = False
    hosting_client: Any = None  # a HostingClient; created from the configuration when None
    runner: Callable[[str, Path | None], subprocess.CompletedProcess] | None = None  # runs hook commands


class Publisher:
    """Base class for publishers; ``requires`` lists optional modules the publisher needs."""

    name: ClassVar[str] = ""
    description: ClassVar[str] = ""
    requires: ClassVar[tuple[str, ...]] = ()

    def __init__(self, config: ProjectConfig):
        self.config = config

    def missing_requirements(self) -> list[str]:
        return [module for module in self.requires if not module_available(module)]

    def publish(self, plan: ReleasePlan, context: PublishContext) -> str:
        raise NotImplementedError


def discover_plugins() -> dict[str, tuple[type[Publisher], str]]:
    """Publishers registered by installed distributions: ``{name: (class, distribution name)}``."""
    found: dict[str, tuple[type[Publisher], str]] = {}
    for entry_point in importlib_metadata.entry_points().get(ENTRY_POINT_GROUP, ()):
        if entry_point.name in found:
            continue
        try:
            loaded = entry_point.load()
        except Exception as exc:  # noqa: BLE001 - a broken plugin must not break releasebot
            log.warning("cannot load publisher plugin %r (%s): %s", entry_point.name, entry_point.value, exc)
            continue
        if not (isinstance(loaded, type) and issubclass(loaded, Publisher)):
            log.warning("ignoring plugin %r: %s is not a Publisher subclass", entry_point.name, entry_point.value)
            continue
        found[entry_point.name] = (loaded, entry_point.dist.name if entry_point.dist else "unknown")
    return found


def _registry() -> dict[str, tuple[type[Publisher], str]]:
    from releasebot.publishers import BUILTIN_PUBLISHERS

    registry = {cls.name: (cls, BUILTIN_ORIGIN) for cls in BUILTIN_PUBLISHERS}
    for name, (cls, origin) in discover_plugins().items():
        if name in registry:
            log.warning("ignoring plugin publisher %r from %s: the name is used by a built-in publisher", name, origin)
        else:
            registry[name] = (cls, origin)
    return registry


def available_publishers() -> dict[str, type[Publisher]]:
    return {name: cls for name, (cls, _origin) in _registry().items()}


def publisher_origins() -> dict[str, str]:
    """Where each available publisher comes from (distribution name or built-in)."""
    return {name: origin for name, (_cls, origin) in _registry().items()}


def get_publisher(name: str) -> type[Publisher]:
    publishers = available_publishers()
    if name not in publishers:
        raise PluginError(f"unknown publisher {name!r}; available: {', '.join(sorted(publishers))}")
    return publishers[name]
