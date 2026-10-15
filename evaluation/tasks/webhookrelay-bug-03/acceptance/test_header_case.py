import json
from datetime import datetime, timezone

import httpx
import pytest

from webhookrelay.app import create_app
from webhookrelay.clock import FixedClock, to_epoch
from webhookrelay.config import Source
from webhookrelay.payloads import Event, normalise
from webhookrelay.replay import ArchivedRequest, replay
from webhookrelay.routing import Router, Rule
from webhookrelay.signatures import SignatureError, authenticate, sign_payload
from webhookrelay.transports import HttpxTransport

T0 = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
SECRET = "src-secret-3c2b1a0f9e8d7c6b5a4f3e2d1c0b9a8f"


@pytest.fixture
def relay():
    delivered = []

    def handler(request):
        delivered.append(request.url.host)
        return httpx.Response(200)

    config = {
        "sources": {"github": {}, "acme": {"secret": SECRET}},
        "targets": {name: {"url": f"https://{name}.example/in"} for name in ("ci", "pager", "archive")},
        "rules": [
            {"name": "prod", "headers": {"x-env": "prod*"}, "targets": ["pager"], "priority": 5, "continue": True},
            {"name": "pushes", "events": ["push"], "targets": ["ci"], "priority": 1},
            {"name": "catch-all", "targets": ["archive"]},
        ],
    }
    app = create_app(config, transport=HttpxTransport(transport=httpx.MockTransport(handler)),
                     clock=FixedClock(T0), start_scheduler=False)
    return app, delivered


def test_github_headers_are_recognised(relay):
    app, delivered = relay
    headers = {"Content-Type": "application/json", "X-GitHub-Event": "push",
               "X-GitHub-Delivery": "72d3162e-cc78-11e3-81ab-4c9367dc0958"}
    response = app.test_client().post("/hooks/github", data=b'{"ref": "refs/heads/main"}', headers=headers)
    assert response.status_code == 202
    payload = response.get_json()
    assert payload["type"] == "push"
    assert payload["event"] == "72d3162e-cc78-11e3-81ab-4c9367dc0958"
    assert delivered == ["ci.example"]


def test_header_routing_condition_with_lower_case_name(relay):
    app, delivered = relay
    headers = {"Content-Type": "application/json", "X-Env": "production", "X-GitHub-Event": "push"}
    response = app.test_client().post("/hooks/github", data=b"{}", headers=headers)
    assert response.status_code == 202
    assert [d["target"] for d in response.get_json()["deliveries"]] == ["pager", "ci"]
    assert delivered == ["pager.example", "ci.example"]


@pytest.mark.parametrize(
    "headers",
    [
        {"content-type": "application/json", "x-event-type": "order.created", "x-event-id": "e-1"},
        {"CONTENT-TYPE": "application/json", "X-EVENT-TYPE": "order.created", "X-EVENT-ID": "e-1"},
        {"Content-type": "application/json", "x-Event-Type": "order.created", "X-Event-id": "e-1"},
    ],
)
def test_normalise_with_any_header_spelling(headers):
    event = normalise("shop", headers, b'{"total": 3}', T0)
    assert (event.type, event.id, event.data) == ("order.created", "e-1", {"total": 3})


def test_github_style_headers_in_normalise_and_routing():
    event = normalise("github", {"x-github-event": "issues", "X-GITHUB-DELIVERY": "d-9", "content-type": "text/plain"},
                      b"hello", T0)
    assert (event.type, event.id, event.data) == ("issues", "d-9", {"text": "hello"})
    rule = Rule.from_dict({"targets": ["t"], "headers": {"X-Env": "prod*"}})
    assert rule.matches(Event("s", "x", "1", {}, T0, {"x-env": "production"}))
    assert not rule.matches(Event("s", "x", "1", {}, T0, {"x-env": "staging"}))
    assert Router([Rule.from_dict({"targets": ["t"], "headers": {"x-team": "core"}})]).route(
        Event("s", "x", "1", {}, T0, {"X-Team": "core"})) == ["t"]


def test_authentication_headers_in_any_case():
    body = b'{"id": "a-1"}'
    ts = to_epoch(T0)
    headers = {"x-relay-signature": sign_payload(SECRET, body, ts), "x-relay-timestamp": str(ts)}
    assert authenticate(Source("acme", secret=SECRET), headers, body, clock=FixedClock(T0)) is None
    headers["X-RELAY-SIGNATURE"] = headers.pop("x-relay-signature").replace("sha256=", "sha256=0")
    with pytest.raises(SignatureError):
        authenticate(Source("acme", secret=SECRET), headers, body, clock=FixedClock(T0))
    with pytest.raises(SignatureError, match="bearer"):
        authenticate(Source("api", jwt_issuers={"x": SECRET}), {"authorization": "Basic abc"}, body)


def test_replaying_archives_with_lower_case_headers(relay):
    app, delivered = relay
    body = json.dumps({"id": "o-5"}).encode()
    ts = to_epoch(T0)
    archived = [
        ArchivedRequest("github", b'{"zen": "x"}', {"content-type": "application/json", "x-github-event": "push"}),
        ArchivedRequest("acme", body, {"content-type": "application/json",
                                       "x-relay-signature": sign_payload(SECRET, body, ts),
                                       "x-relay-timestamp": str(ts)}),
    ]
    results = replay(app, archived)
    assert [r.status for r in results] == [202, 202] and results[1].event_id == "o-5"
    assert delivered == ["ci.example", "archive.example"]
