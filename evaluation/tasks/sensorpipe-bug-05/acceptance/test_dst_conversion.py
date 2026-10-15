import io
from datetime import datetime, timedelta, timezone

import pytest

from sensorpipe.ingest import read_csv
from sensorpipe.readings import parse_timestamp
from sensorpipe.timeutil import get_zone, to_utc

UTC = timezone.utc


@pytest.mark.parametrize("local, zone, expected", [
    (datetime(2024, 7, 1, 12, 0), "Europe/Berlin", datetime(2024, 7, 1, 10, 0, tzinfo=UTC)),
    (datetime(2024, 1, 15, 12, 0), "Europe/Berlin", datetime(2024, 1, 15, 11, 0, tzinfo=UTC)),
    (datetime(2024, 7, 4, 8, 0), "America/New_York", datetime(2024, 7, 4, 12, 0, tzinfo=UTC)),
    (datetime(2024, 7, 1, 12, 0), "Australia/Sydney", datetime(2024, 7, 1, 2, 0, tzinfo=UTC)),
    (datetime(2024, 1, 1, 12, 0), "Australia/Sydney", datetime(2024, 1, 1, 1, 0, tzinfo=UTC)),
    (datetime(2024, 7, 1, 12, 0), "Asia/Kolkata", datetime(2024, 7, 1, 6, 30, tzinfo=UTC)),
    (datetime(2024, 7, 1, 12, 0), "UTC", datetime(2024, 7, 1, 12, 0, tzinfo=UTC)),
])
def test_naive_local_times(local, zone, expected):
    result = to_utc(local, zone)
    assert result == expected and result.utcoffset() == timedelta(0)


def test_transition_days():
    assert to_utc(datetime(2024, 3, 31, 1, 30), "Europe/Berlin") == datetime(2024, 3, 31, 0, 30, tzinfo=UTC)
    assert to_utc(datetime(2024, 3, 31, 3, 30), "Europe/Berlin") == datetime(2024, 3, 31, 1, 30, tzinfo=UTC)
    assert to_utc(datetime(2024, 10, 27, 1, 30), "Europe/Berlin") == datetime(2024, 10, 26, 23, 30, tzinfo=UTC)
    assert to_utc(datetime(2024, 10, 27, 4, 0), "Europe/Berlin") == datetime(2024, 10, 27, 3, 0, tzinfo=UTC)


def test_aware_values_are_unaffected():
    berlin = get_zone("Europe/Berlin")
    assert to_utc(datetime(2024, 7, 1, 12, 0, tzinfo=berlin), "America/New_York") == \
        datetime(2024, 7, 1, 10, 0, tzinfo=UTC)
    assert parse_timestamp("2024-07-01T12:00:00+02:00", tz="Australia/Sydney") == datetime(2024, 7, 1, 10, tzinfo=UTC)


def test_ingestion_and_parsing_use_site_offsets():
    assert parse_timestamp("2024-07-01 12:00:00", tz="Europe/Berlin") == datetime(2024, 7, 1, 10, tzinfo=UTC)
    assert parse_timestamp("01.07.2024 12:00", tz="Europe/Berlin", fmt="DD.MM.YYYY HH:mm") == \
        datetime(2024, 7, 1, 10, tzinfo=UTC)
    readings = read_csv(io.StringIO("timestamp,value\n2024-01-15 12:00:00,1\n2024-07-15 12:00:00,2\n"),
                        device_id="TT-9", channel="temp", unit="degC", tz="Europe/Berlin")
    assert [r.timestamp for r in readings] == [datetime(2024, 1, 15, 11, tzinfo=UTC),
                                               datetime(2024, 7, 15, 10, tzinfo=UTC)]
