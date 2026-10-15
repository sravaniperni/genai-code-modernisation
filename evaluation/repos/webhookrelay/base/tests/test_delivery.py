import json
import logging
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import httpx
from conftest import T0, TARGET_SECRET, Recorder, make_config

from webhookrelay.clock import isoformat_z
from webhookrelay.config import load_config
from webhookrelay.delivery import Dispatcher, build_delivery_url
from webhookrelay.payloads import Event
from webhookrelay.signatures import verify_hmac, verify_jwt
from webhookrelay.transports import HttpxTransport


def order_event(type_="order.created"):
    return Event("shop", type_, "evt-1", {"title": "Big order", "total": 120}, T0, {})


def dispatcher(recorder, clock, **overrides):
    transport = HttpxTransport(transport=httpx.MockTransport(recorder))
    return Dispatcher(load_config(make_config(**overrides)), transport=transport, clock=clock)


def test_signed_json_and_rendered_deliveries(recorder, clock):
    records = dispatcher(recorder, clock).dispatch(order_event())
    assert [(r.target, r.status, r.ok) for r in records] == [("audit", 200, True), ("chat", 200, True)]
    audit, chat = recorder.requests
    assert audit.headers["content-type"] == "application/json"
    verify_hmac(TARGET_SECRET, audit.content, audit.headers["x-relay-signature"], audit.headers["x-relay-timestamp"],
                clock=clock)
    assert json.loads(audit.content)["data"]["total"] == 120
    query = parse_qs(urlsplit(str(audit.url)).query)
    assert query["team"] == ["core"] and query["delivery"] == [records[0].delivery_id]
    assert chat.headers["content-type"].startswith("text/plain")
    assert chat.content.decode() == "[shop] order.created: Big order\nhttps://relay.example/admin/events/evt-1"


def test_failed_delivery_is_retried_later(clock):
    recorder = Recorder(httpx.Response(503), httpx.Response(204))
    relay = dispatcher(recorder, clock)
    [record] = relay.dispatch(order_event("user.created"))
    assert (record.status, record.ok, record.attempt) == (503, False, 1)
    assert record.next_retry_at is not None and record.next_retry_at > record.attempted_at
    assert relay.scheduler.describe()["pending"] == 1
    assert relay.scheduler.run_pending() == 0
    clock.advance(3600)
    assert relay.scheduler.run_pending() == 1
    assert [(r.attempt, r.status) for r in relay.attempts] == [(1, 503), (2, 204)]
    assert recorder.requests[1].headers["x-relay-attempt"] == "2"


def test_retry_after_header_is_honoured(clock, caplog):
    recorder = Recorder(httpx.Response(429, headers={"Retry-After": "120"}), httpx.Response(500))
    relay = dispatcher(recorder, clock)
    [first] = relay.dispatch(order_event("user.created"))
    assert first.next_retry_at - first.attempted_at == timedelta(seconds=120)
    assert first.to_dict()["next_retry_at"] == "2026-01-01T12:02:00Z"
    clock.advance(120)
    with caplog.at_level(logging.WARNING, logger="webhookrelay"):
        relay.scheduler.run_pending()
    assert relay.attempts[-1].status == 500
    assert any("failed (attempt 2)" in r.getMessage() for r in caplog.records)


def test_connection_errors_and_attempt_limit(clock):
    def refuse(request):
        raise httpx.ConnectError("connection refused", request=request)

    relay = dispatcher(refuse, clock, retry={"max_attempts": 1})
    [record] = relay.dispatch(order_event("user.created"))
    assert record.status is None and "ConnectError" in record.error
    assert record.next_retry_at is None
    assert relay.scheduler.describe()["pending"] == 0
    stats = {row["name"]: row for row in relay.stats()}
    assert stats["audit"]["failed"] == 1 and stats["chat"]["delivered"] == 0


def test_jwt_authenticated_target(recorder, clock):
    targets = {"crm": {"url": "https://crm.example/in", "auth": "jwt", "secret": TARGET_SECRET}}
    relay = dispatcher(recorder, clock, targets=targets, rules=[{"targets": ["crm"]}])
    [record] = relay.dispatch(order_event())
    scheme, token = recorder.requests[0].headers["authorization"].split(" ")
    assert scheme == "Bearer"
    claims = verify_jwt(token, {"webhookrelay": TARGET_SECRET}, audience="crm", leeway=10**10)
    assert claims["sub"] == record.delivery_id


def test_unrouted_events_are_logged(recorder, clock, caplog):
    relay = dispatcher(recorder, clock, rules=[{"events": ["order.*"], "targets": ["audit"]}])
    with caplog.at_level(logging.WARNING, logger="webhookrelay"):
        assert relay.dispatch(order_event("user.created")) == []
    assert "no route" in caplog.text
    assert recorder.requests == []


def test_build_delivery_url_keeps_query_and_fragment():
    url = build_delivery_url("https://h.example/hook?token=abc#frag", {"delivery": "d1", "skip": None, "n": 3})
    parts = urlsplit(url)
    assert parts.fragment == "frag"
    assert parse_qs(parts.query) == {"token": ["abc"], "delivery": ["d1"], "n": ["3"]}
    assert build_delivery_url("https://h.example/hook", {}) == "https://h.example/hook"


def test_attempt_record_serialisation(recorder, clock):
    [record, _] = dispatcher(recorder, clock).dispatch(order_event())
    data = record.to_dict()
    assert data["attempted_at"] == isoformat_z(T0) == "2026-01-01T12:00:00Z"
    assert data["next_retry_at"] is None and data["ok"] is True
