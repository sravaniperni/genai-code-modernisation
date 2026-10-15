from datetime import datetime, timezone

from webhookrelay.payloads import normalise, parse_xml
from webhookrelay.routing import Router, Rule

T0 = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)

CI_EVENT = """<?xml version="1.0"?>
<event type="build.finished" id="b-77" pipeline="main">
  <headers>
    <header name="X-Env">production</header>
    <header name="X-Team"> payments </header>
  </headers>
  <data>
    <status>failed</status>
    <duration>  93 </duration>
    <commit><sha>abc123</sha><author><name>Ann</name><email>ann@example.com</email></author></commit>
    <stage>build</stage>
    <stage>test</stage>
    <stage><name>deploy</name><skipped>true</skipped></stage>
    <note/>
    <comment>   </comment>
  </data>
</event>
"""

ERP_EVENT = """<order-event type="order.shipped">
  <order><number>SO-1001</number><lines><line>A</line><line>B</line></lines></order>
  <carrier>DHL</carrier>
</order-event>
"""


def test_envelope_with_data_and_headers():
    parsed = parse_xml(CI_EVENT)
    assert parsed == {
        "_type": "build.finished",
        "_id": "b-77",
        "_pipeline": "main",
        "_headers": {"X-Env": "production", "X-Team": "payments"},
        "status": "failed",
        "duration": "93",
        "commit": {"sha": "abc123", "author": {"name": "Ann", "email": "ann@example.com"}},
        "stage": ["build", "test", {"name": "deploy", "skipped": "true"}],
        "note": "",
        "comment": "",
    }


def test_envelope_without_data_element():
    assert parse_xml(ERP_EVENT) == {
        "_type": "order.shipped",
        "order": {"number": "SO-1001", "lines": {"line": ["A", "B"]}},
        "carrier": "DHL",
    }


def test_single_leaf_and_attribute_only_documents():
    assert parse_xml("<ping>pong</ping>") == {}
    assert parse_xml('<ping id="p1"/>') == {"_id": "p1"}
    assert parse_xml("<event><data><only>value</only></data></event>") == {"only": "value"}
    assert parse_xml("<event><data><wrap><leaf>x</leaf></wrap></data></event>") == {"wrap": {"leaf": "x"}}


def test_normalise_xml_event():
    event = normalise("ci", {"Content-Type": "application/xml"}, CI_EVENT.encode(), T0)
    assert (event.type, event.id) == ("build.finished", "b-77")
    assert event.headers["X-Env"] == "production" and event.headers["Content-Type"] == "application/xml"
    assert "_headers" not in event.data and "_type" not in event.data
    assert event.data["commit"]["author"]["name"] == "Ann"
    rule = Rule.from_dict({"targets": ["pager"], "headers": {"X-Env": "prod*"}, "where": {"status": "failed"}})
    assert Router([rule]).route(event) == ["pager"]


def test_request_headers_win_over_xml_headers():
    event = normalise("ci", {"Content-Type": "text/xml", "X-Env": "staging"}, CI_EVENT.encode(), T0)
    assert event.headers["X-Env"] == "staging" and event.headers["X-Team"] == "payments"
