import importlib.metadata
import json
import re
import threading
from datetime import datetime, timezone
from urllib.parse import parse_qs, unquote, urlsplit

import httpx
import pytest

from webhookrelay.app import create_app
from webhookrelay.clock import FixedClock, to_epoch
from webhookrelay.delivery import build_delivery_url
from webhookrelay.signatures import sign_payload
from webhookrelay.transports import HttpxTransport

T0 = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
SECRET = "src-secret-1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d"
ISO_Z = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")


def handler(request):
    if "broken" in request.url.host:
        raise httpx.ConnectError("refused <by firewall>", request=request)
    return httpx.Response(200)


def make_app(**kwargs):
    config = {
        "sources": {"acme": {"secret": SECRET}, "open": {}},
        "targets": {
            "audit": {"url": "https://audit.example/in?team=core"},
            "ops & alerts": {"url": "https://broken.example/in", "max_attempts": 1},
        },
        "rules": [{"name": "all", "targets": ["audit", "ops & alerts"]}],
        "admin_token": "t0ken",
    }
    transport = HttpxTransport(transport=httpx.MockTransport(handler))
    kwargs.setdefault("start_scheduler", False)
    return create_app(config, transport=transport, clock=FixedClock(T0), **kwargs)


def test_versions_are_pinned():
    assert importlib.metadata.version("Flask") == "3.1.2"
    assert importlib.metadata.version("Werkzeug") == "3.1.3"


def test_webhook_intake_response():
    client = make_app().test_client()
    body = json.dumps({"type": "order.created", "id": "o-9"}).encode()
    ts = to_epoch(T0)
    headers = {"X-Relay-Signature": sign_payload(SECRET, body, ts), "X-Relay-Timestamp": str(ts),
               "Content-Type": "application/json"}
    response = client.post("/hooks/acme", data=body, headers=headers)
    assert response.status_code == 202
    payload = response.get_json()
    assert payload["event"] == "o-9" and payload["type"] == "order.created"
    audit, ops = payload["deliveries"]
    assert set(audit) == {"delivery", "target", "event", "attempt", "status", "ok", "error", "attempted_at",
                          "next_retry_at"}
    assert (audit["target"], audit["status"], audit["ok"], audit["attempted_at"]) == ("audit", 200, True,
                                                                                      "2026-01-01T12:00:00Z")
    assert ops["status"] is None and "ConnectError" in ops["error"] and ops["next_retry_at"] is None
    headers["X-Relay-Signature"] = "sha256=" + "0" * 64
    response = client.post("/hooks/acme", data=body, headers=headers)
    assert response.status_code == 401 and response.get_json() == {"error": "signature mismatch"}
    assert client.post("/hooks/missing", data=body).status_code == 404
    response = client.post("/hooks/open", data=b"{nope", headers={"Content-Type": "application/json"})
    assert response.status_code == 400 and "invalid JSON" in response.get_json()["error"]


def test_status_page():
    client = make_app().test_client()
    client.post("/hooks/open", data=b'{"type": "x"}', headers={"Content-Type": "application/json"})
    assert client.get("/admin/status").status_code == 403
    page = client.get("/admin/status", headers={"X-Admin-Token": "t0ken"}).get_data(as_text=True)
    links = dict(
        (unquote(href.split("target=", 1)[1]), text)
        for href, text in re.findall(r'<a href="(/admin/status\?target=[^"]*)">([^<]*)</a>', page)
    )
    assert links == {"audit": "audit", "ops & alerts": "ops &amp; alerts"}
    assert '<span class="badge ok" title="HTTP 200">ok</span>' in page
    assert "refused &lt;by firewall&gt;" in page and "<by firewall>" not in page
    assert '<span class="badge failing"' in page
    assert "drop-pings (builtin)" in page and "webhookrelay 1.4.0" in page
    filtered = client.get("/admin/status?target=audit&token=t0ken").get_data(as_text=True)
    assert "Recent attempts for audit" in filtered


def test_status_json_format():
    client = make_app().test_client()
    client.post("/hooks/open", data=b'{"type": "x", "id": "e1"}', headers={"Content-Type": "application/json"})
    status = client.get("/admin/status.json", headers={"X-Admin-Token": "t0ken"}).get_json()
    assert status["now"] == "2026-01-01T12:00:00Z"
    assert status["started_at"] == "2026-01-01T12:00:00Z"
    assert status["received"] == 1 and status["version"] == "1.4.0"
    first = status["recent"][0]
    assert first["delivery"] and first["event"] == "e1" and first["attempted_at"] == "2026-01-01T12:00:00Z"
    rows = {row["name"]: row for row in status["targets"]}
    assert ISO_Z.match(rows["audit"]["last_attempt_at"])
    assert rows["ops & alerts"]["failed"] == 1
    assert status["scheduler"]["running"] is False
    assert {"name": "redact-secrets", "origin": "builtin"} in status["plugins"]


def test_scheduler_starts_on_first_request():
    app = make_app(start_scheduler=True)
    scheduler = app.extensions["webhookrelay"].dispatcher.scheduler
    try:
        status = app.test_client().get("/admin/status.json?token=t0ken").get_json()
        assert scheduler.running
        assert status["started_at"] == "2026-01-01T12:00:00Z"
        app.test_client().get("/admin/status.json?token=t0ken")
        assert sum(1 for t in threading.enumerate() if t.name == "webhookrelay-retry") == 1
    finally:
        scheduler.stop()


@pytest.mark.parametrize(
    "base, params, expected_query",
    [
        ("https://h.example/in", {"delivery": "d1"}, {"delivery": ["d1"]}),
        ("https://h.example/in?team=core", {"label": "p1+urgent", "q": "a b&c=d"},
         {"team": ["core"], "label": ["p1+urgent"], "q": ["a b&c=d"]}),
        ("https://h.example/in", {"city": "Zürich", "path": "/x/y?z", "skip": None},
         {"city": ["Zürich"], "path": ["/x/y?z"]}),
        ("https://h.example/in", {"n": 3, "flag": True}, {"n": ["3"], "flag": ["True"]}),
    ],
)
def test_delivery_urls(base, params, expected_query):
    url = build_delivery_url(base, params)
    parts = urlsplit(url)
    assert (parts.scheme, parts.netloc, parts.path) == ("https", "h.example", "/in")
    assert parse_qs(parts.query) == expected_query


def test_delivery_url_keeps_fragment_and_plain_urls():
    assert urlsplit(build_delivery_url("https://h.example/in?a=1#top", {"b": "2"})).fragment == "top"
    assert build_delivery_url("https://h.example/in", {}) == "https://h.example/in"
    assert build_delivery_url("https://h.example/in", {"skip": None}) == "https://h.example/in"
