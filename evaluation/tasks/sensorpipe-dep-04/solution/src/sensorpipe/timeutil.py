"""Time-zone helpers. Internally every timestamp is an aware UTC ``datetime``; naive values are site-local."""

from __future__ import annotations

from datetime import datetime, timezone, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import arrow

UTC = timezone.utc


def get_zone(name: str) -> tzinfo:
    """Return the ``tzinfo`` for an IANA zone name (``"UTC"`` and ``"Z"`` map to :data:`UTC`)."""
    if name.strip().upper() in ("UTC", "Z"):
        return UTC
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"unknown time zone {name!r}") from exc


def to_utc(value: datetime, tz: str = "UTC") -> datetime:
    """Normalise ``value`` to aware UTC; naive values are wall-clock times in ``tz``."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=get_zone(tz))
    return value.astimezone(UTC)


def epoch_seconds(value: datetime) -> int:
    """Whole seconds since the Unix epoch (fractions are truncated)."""
    return arrow.get(to_utc(value)).int_timestamp


def floor_time(value: datetime, seconds: int) -> datetime:
    """Round ``value`` down to a multiple of ``seconds`` since the epoch."""
    if seconds <= 0:
        raise ValueError("seconds must be positive")
    epoch = epoch_seconds(value)
    return datetime.fromtimestamp(epoch - epoch % seconds, tz=UTC)


def format_local(value: datetime, tz: str, fmt: str = "YYYY-MM-DD HH:mm") -> str:
    """Format an instant as wall-clock time of zone ``tz`` (arrow format tokens)."""
    get_zone(tz)
    return arrow.get(to_utc(value)).to(tz).format(fmt)
