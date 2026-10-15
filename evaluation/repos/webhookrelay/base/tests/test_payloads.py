import json

import pytest
from conftest import T0

from webhookrelay.clock import isoformat_z
from webhookrelay.payloads import PayloadError, decode_body, normalise, parse_content_type, parse_xml


def test_json_event_uses_headers_for_type_and_id():
    body = json.dumps({"order": {"id": 42, "total": "19.90"}}).encode()
    headers = {"Content-Type": "application/json", "X-Event-Type": "order.created", "X-Event-Id": "evt-1"}
    event = normalise("shop", headers, body, T0)
    assert (event.source, event.type, event.id) == ("shop", "order.created", "evt-1")
    assert event.data == {"order": {"id": 42, "total": "19.90"}}
    assert event.to_dict()["received_at"] == "2026-01-01T12:00:00Z"
    assert isoformat_z(event.received_at) == "2026-01-01T12:00:00Z"


def test_type_and_id_fall_back_to_payload_then_digest():
    body = b'{"type": "invoice.paid", "amount": 3}'
    event = normalise("billing", {"Content-Type": "application/json"}, body, T0)
    assert event.type == "invoice.paid"
    again = normalise("billing", {"Content-Type": "application/json"}, body, T0)
    assert event.id == again.id and len(event.id) == 16
    other = normalise("shipping", {"Content-Type": "application/json"}, body, T0)
    assert other.id != event.id


def test_form_bodies_and_payload_envelopes():
    form = decode_body(b"name=relay&empty=", "application/x-www-form-urlencoded")
    assert form == {"name": "relay", "empty": ""}
    envelope = decode_body(b"payload=%7B%22action%22%3A%22opened%22%7D", "application/x-www-form-urlencoded")
    assert envelope == {"action": "opened"}


def test_content_type_parameters():
    assert parse_content_type("application/json") == ("application/json", {})
    assert parse_content_type('Text/Plain; Charset="latin-1"') == ("text/plain", {"charset": "latin-1"})
    assert parse_content_type(None) == ("application/octet-stream", {})
    assert decode_body("café".encode("latin-1"), "text/plain; charset=latin-1") == {"text": "café"}


def test_xml_payloads():
    xml = (
        '<event type="build.finished" id="b-17"><data><status>passed</status>'
        "<repo><name>relay</name><branch>main</branch></repo><tag>a</tag><tag>b</tag></data></event>"
    )
    data = parse_xml(xml)
    assert data["_type"] == "build.finished"
    assert data["status"] == "passed"
    assert data["repo"] == {"name": "relay", "branch": "main"}
    assert data["tag"] == ["a", "b"]
    event = normalise("ci", {"Content-Type": "application/xml"}, xml.encode(), T0)
    assert (event.type, event.id) == ("build.finished", "b-17")
    assert "_type" not in event.data


def test_undecodable_bodies_are_rejected():
    with pytest.raises(PayloadError, match="JSON"):
        decode_body(b"{nope", "application/json")
    with pytest.raises(PayloadError, match="unsupported"):
        decode_body(b"\x00\x01", "application/octet-stream")
    with pytest.raises(PayloadError, match="XML"):
        decode_body(b"<a><b></a>", "text/xml")
