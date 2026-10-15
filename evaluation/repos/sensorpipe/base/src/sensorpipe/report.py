"""Report export: per-channel summaries as CSV or JSON."""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import arrow
import numpy as np

from sensorpipe.calibration import format_metadata
from sensorpipe.readings import ReadingBatch
from sensorpipe.timeutil import epoch_seconds

CSV_FIELDS = ["device_id", "channel", "unit", "count", "first", "last", "first_epoch", "last_epoch",
              "mean", "min", "max", "anomalies"]


@dataclass(frozen=True)
class ChannelSummary:
    device_id: str
    channel: str
    unit: str
    count: int
    first: datetime
    last: datetime
    mean: float
    minimum: float
    maximum: float
    anomalies: int = 0


def summarise(batch: ReadingBatch, anomalies: int = 0) -> ChannelSummary:
    """Summarise a non-empty batch; NaN readings count but do not enter the statistics."""
    if not len(batch):
        raise ValueError("cannot summarise an empty batch")
    values = batch.values()
    valid = values[~np.isnan(values)]
    stats = (float(valid.mean()), float(valid.min()), float(valid.max())) if valid.size else (np.nan,) * 3
    first, last = batch[0], batch[-1]
    return ChannelSummary(first.device_id, first.channel, first.unit, len(batch), first.timestamp, last.timestamp,
                          *stats, anomalies=anomalies)


def summary_rows(summaries: Iterable[ChannelSummary]) -> list[dict[str, Any]]:
    return [
        {
            "device_id": s.device_id, "channel": s.channel, "unit": s.unit, "count": s.count,
            "first": s.first.isoformat(), "last": s.last.isoformat(),
            "first_epoch": epoch_seconds(s.first), "last_epoch": epoch_seconds(s.last),
            "mean": round(s.mean, 4), "min": round(s.minimum, 4), "max": round(s.maximum, 4),
            "anomalies": s.anomalies,
        }
        for s in summaries
    ]


def report_filename(start: datetime, extension: str = "csv", prefix: str = "sensorpipe-report") -> str:
    """File name for a report covering data from ``start``: ``<prefix>-<epoch seconds>.<extension>``."""
    return f"{prefix}-{arrow.get(start).format('X')}.{extension}"


def export_csv(summaries: Iterable[ChannelSummary]) -> str:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=CSV_FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(summary_rows(summaries))
    return out.getvalue()


def export_json(summaries: Iterable[ChannelSummary], generated_at: datetime,
                calibration_format: str | None = None) -> str:
    payload: dict[str, Any] = {
        "generated_at": generated_at.isoformat(),
        "generated_epoch": epoch_seconds(generated_at),
        "channels": summary_rows(summaries),
    }
    if calibration_format:
        payload["calibration_format"] = format_metadata(calibration_format)
    return json.dumps(payload, indent=2, sort_keys=True)

