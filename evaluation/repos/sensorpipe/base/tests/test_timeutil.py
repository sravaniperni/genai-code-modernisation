from datetime import datetime, timezone

import pytest

from sensorpipe.timeutil import epoch_seconds, floor_time, format_local, get_zone, to_utc

UTC = timezone.utc


def test_to_utc():
    value = datetime(2024, 1, 15, 9, 0, tzinfo=get_zone("Europe/Berlin"))
    assert to_utc(value) == datetime(2024, 1, 15, 8, 0, tzinfo=UTC)
    assert to_utc(datetime(2024, 1, 15, 7, 0), "America/New_York") == datetime(2024, 1, 15, 12, 0, tzinfo=UTC)


def test_unknown_zone_is_rejected():
    with pytest.raises(ValueError):
        get_zone("Mars/Olympus_Mons")


def test_epoch_seconds_and_floor():
    value = datetime(2024, 3, 10, 11, 30, 0, 750000, tzinfo=UTC)
    assert epoch_seconds(value) == 1710070200
    assert floor_time(value, 3600) == datetime(2024, 3, 10, 11, 0, tzinfo=UTC)


def test_format_local():
    assert format_local(datetime(2024, 1, 15, 12, 0, tzinfo=UTC), "Europe/Berlin") == "2024-01-15 13:00"
