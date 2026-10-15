"""CSV and JSON ingestion of sensor readings."""

from __future__ import annotations

import csv
import io
import json
import math
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any, TextIO

from sensorpipe.errors import IngestError
from sensorpipe.readings import Reading, ReadingBatch, parse_timestamp

_MISSING = {"", "nan", "null", "none", "-"}


def _value(raw: Any) -> tuple[float, str]:
    if raw is None or (isinstance(raw, str) and raw.strip().lower() in _MISSING):
        return math.nan, "missing"
    return float(raw), "good"


def read_csv(
    source: str | Path | TextIO, *, device_id: str | None = None, channel: str | None = None,
    unit: str | None = None, tz: str = "UTC", timestamp_format: str | None = None, delimiter: str = ",",
) -> list[Reading]:
    """Read readings from CSV with columns ``timestamp`` and ``value`` (``device_id``, ``channel``, ``unit``
    and ``quality`` columns are optional and default to the keyword arguments)."""
    if isinstance(source, (str, Path)):
        with open(source, newline="", encoding="utf-8") as handle:
            return read_csv(handle, device_id=device_id, channel=channel, unit=unit, tz=tz,
                            timestamp_format=timestamp_format, delimiter=delimiter)
    reader = csv.DictReader(source, delimiter=delimiter)
    missing = {"timestamp", "value"} - set(reader.fieldnames or ())
    if missing:
        raise IngestError(f"CSV input lacks required column(s): {', '.join(sorted(missing))}")
    readings = []
    for lineno, row in enumerate(reader, start=2):
        try:
            value, quality = _value(row.get("value"))
            ts = parse_timestamp(row["timestamp"], tz=tz, fmt=timestamp_format)
        except (ValueError, IngestError) as exc:
            raise IngestError(f"line {lineno}: {exc}") from exc
        dev, chan, u = row.get("device_id") or device_id, row.get("channel") or channel, row.get("unit") or unit
        if not (dev and chan and u):
            raise IngestError(f"line {lineno}: device_id, channel and unit are required")
        readings.append(Reading(dev, chan, ts, value, u, row.get("quality") or quality))
    return readings


def read_json(source: str | Path | TextIO, *, tz: str = "UTC") -> list[Reading]:
    """Read either a list of reading objects or a device document ``{"device_id", "channel", "unit",
    "readings": [{"ts", "value"}, ...]}``."""
    if isinstance(source, (str, Path)):
        source = io.StringIO(Path(source).read_text(encoding="utf-8"))
    try:
        data = json.load(source)
    except json.JSONDecodeError as exc:
        raise IngestError(f"invalid JSON: {exc}") from exc
    defaults: dict[str, Any] = {}
    if isinstance(data, dict):
        defaults = {k: data.get(k) for k in ("device_id", "channel", "unit")}
        data = data.get("readings", [])
    readings = []
    for i, item in enumerate(data):
        merged = {**defaults, **{k: v for k, v in item.items() if v is not None}}
        try:
            value, quality = _value(merged.get("value"))
            ts = parse_timestamp(merged.get("ts", merged.get("timestamp")), tz=tz)
            readings.append(Reading(merged["device_id"], merged["channel"], ts, value, merged["unit"],
                                    merged.get("quality", quality)))
        except (KeyError, TypeError, ValueError, IngestError) as exc:
            raise IngestError(f"reading #{i}: {exc!r}") from exc
    return readings


def load_file(path: str | Path, **options: Any) -> list[Reading]:
    suffix = Path(path).suffix.lower()
    if suffix == ".csv":
        return read_csv(path, **options)
    if suffix == ".json":
        return read_json(path, tz=options.get("tz", "UTC"))
    raise IngestError(f"unsupported input format {suffix!r}")


def group_batches(readings: Iterable[Reading]) -> dict[tuple[str, str], ReadingBatch]:
    """Split readings into per-(device, channel) batches."""
    groups: dict[tuple[str, str], list[Reading]] = defaultdict(list)
    for reading in readings:
        groups[(reading.device_id, reading.channel)].append(reading)
    return {key: ReadingBatch(items) for key, items in sorted(groups.items())}
