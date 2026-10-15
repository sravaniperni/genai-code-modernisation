from datetime import datetime, timezone

import pytest

from jobqueue.errors import InvalidJobSpec, PayloadTooLarge
from jobqueue.payload import check_payload_size, decode_payload, encode_payload, payload_size


def test_encoding_is_compact_and_key_sorted():
    assert encode_payload({"b": 1, "a": [1, 2]}) == '{"a":[1,2],"b":1}'
    assert decode_payload(encode_payload({"b": 1, "a": [1, 2]})) == {"a": [1, 2], "b": 1}


def test_dates_are_encoded_as_iso_strings_and_objects_rejected():
    stamp = datetime(2024, 3, 1, 12, 0, tzinfo=timezone.utc)
    assert encode_payload({"at": stamp}) == '{"at":"2024-03-01T12:00:00+00:00"}'
    with pytest.raises(InvalidJobSpec):
        encode_payload({"obj": object()})


def test_payload_size_of_ascii_payload():
    assert payload_size({"k": "v"}) == len('{"k":"v"}')


def test_oversized_payload_rejected():
    assert check_payload_size({"data": "x" * 80}, limit=100) == 91
    with pytest.raises(PayloadTooLarge) as info:
        check_payload_size({"data": "x" * 200}, limit=100)
    assert info.value.limit == 100 and info.value.size > 100
