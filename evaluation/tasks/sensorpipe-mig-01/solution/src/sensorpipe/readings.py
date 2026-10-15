"""The :class:`Reading` model, reading batches and timestamp normalisation."""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

import arrow
import numpy as np

from sensorpipe.errors import IngestError
from sensorpipe.timeutil import UTC, to_utc

#: Epoch values with an absolute value above this are milliseconds rather than seconds.
EPOCH_MS_THRESHOLD = 100_000_000_000
_NUMERIC = re.compile(r"^-?\d+(\.\d+)?$")


@dataclass(frozen=True)
class Reading:
    """One measurement of one channel of one device."""

    device_id: str
    channel: str
    timestamp: datetime
    value: float
    unit: str
    quality: str = "good"

    def __post_init__(self) -> None:
        if self.timestamp.tzinfo is None:
            raise ValueError("Reading.timestamp must be timezone-aware")

    def with_value(self, value: float, unit: str | None = None) -> Reading:
        return replace(self, value=float(value), unit=unit or self.unit)


def from_epoch(value: float) -> datetime:
    """Convert seconds (or milliseconds) since the Unix epoch to an aware UTC datetime."""
    seconds = float(value)
    if abs(seconds) >= EPOCH_MS_THRESHOLD:
        seconds /= 1000.0
    return datetime.fromtimestamp(seconds, tz=UTC)


def parse_timestamp(raw: Any, tz: str = "UTC", fmt: str | None = None) -> datetime:
    """Parse a timestamp from a device payload into aware UTC.

    Accepts datetimes, epoch numbers (seconds or milliseconds, also as strings), ISO 8601 strings and, when
    ``fmt`` is given, arrow-style formatted wall-clock strings. Values without an offset are local to ``tz``.
    """
    if isinstance(raw, datetime):
        return to_utc(raw, tz)
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return from_epoch(raw)
    text = str(raw).strip()
    if not text:
        raise IngestError("empty timestamp")
    try:
        if fmt:
            return to_utc(arrow.get(text, fmt).naive, tz)
        if _NUMERIC.match(text):
            return from_epoch(float(text))
        return to_utc(datetime.fromisoformat(text), tz)
    except ValueError as exc:  # arrow's ParserError is a ValueError too
        raise IngestError(f"unparseable timestamp {text!r}") from exc


class ReadingBatch(Sequence[Reading]):
    """Readings of a single device channel, ordered by timestamp."""

    def __init__(self, readings: Iterable[Reading] = ()):
        self._items = sorted(readings, key=lambda r: r.timestamp)

    def __getitem__(self, index):  # type: ignore[override]
        if isinstance(index, slice):
            return ReadingBatch(self._items[index])
        return self._items[index]

    def __len__(self) -> int:
        return len(self._items)

    def __iter__(self) -> Iterator[Reading]:
        return iter(self._items)

    @property
    def unit(self) -> str | None:
        return self._items[0].unit if self._items else None

    def values(self) -> np.ndarray:
        return np.array([r.value for r in self._items], dtype=np.float_)

    def epochs(self) -> np.ndarray:
        return np.array([r.timestamp.timestamp() for r in self._items], dtype=np.float_)

    @classmethod
    def from_arrays(
        cls, epochs: Iterable[float], values: Iterable[float], *, device_id: str, channel: str, unit: str
    ) -> ReadingBatch:
        """Build a batch from epoch-second and value arrays; NaN values become ``gap`` readings."""
        items = []
        for t, v in zip(epochs, values, strict=True):
            ts = datetime.fromtimestamp(float(t), tz=UTC)
            quality = "gap" if math.isnan(v) else "good"
            items.append(Reading(device_id, channel, ts, float(v), unit, quality))
        return cls(items)
