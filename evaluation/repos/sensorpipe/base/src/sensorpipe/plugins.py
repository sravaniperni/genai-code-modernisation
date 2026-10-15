"""Discovery of third-party anomaly detectors registered as ``sensorpipe.detectors`` entry points."""

from __future__ import annotations

import logging
from typing import Any

import importlib_metadata

from sensorpipe.anomaly import BUILTIN_DETECTORS, Detector
from sensorpipe.errors import ConfigError

ENTRY_POINT_GROUP = "sensorpipe.detectors"
log = logging.getLogger(__name__)


def detector_entry_points() -> list[Any]:
    return list(importlib_metadata.entry_points().get(ENTRY_POINT_GROUP, ()))


def discover_detectors() -> dict[str, type[Detector]]:
    """Built-in detectors plus installed plugins; broken or invalid plugins are skipped with a warning."""
    found: dict[str, type[Detector]] = dict(BUILTIN_DETECTORS)
    for ep in detector_entry_points():
        if ep.name in BUILTIN_DETECTORS:
            log.warning("detector plugin %s would shadow a built-in detector; ignored", ep.name)
            continue
        try:
            obj = ep.load()
        except Exception as exc:  # a broken plugin must not take the pipeline down
            log.warning("cannot load detector plugin %s: %s", ep.name, exc)
            continue
        if not (isinstance(obj, type) and issubclass(obj, Detector)):
            log.warning("detector plugin %s is not a Detector subclass; ignored", ep.name)
            continue
        found[ep.name] = obj
    return found


def create_detector(name: str, **options: Any) -> Detector:
    detectors = discover_detectors()
    if name not in detectors:
        raise ConfigError(f"unknown detector {name!r}; available: {', '.join(sorted(detectors))}")
    return detectors[name](**options)
