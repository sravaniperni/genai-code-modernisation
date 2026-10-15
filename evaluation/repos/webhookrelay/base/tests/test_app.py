import json

import httpx
import pytest
from conftest import SOURCE_SECRET, Recorder, make_config

from webhookrelay.app import create_app
from webhookrelay.clock import to_epoch
from webhookrelay.replay import load_archive, replay
from webhookrelay.signatures import sign_payload
from webhookrelay.transports import HttpxTransport


@pytest.fixture
def app(recorder, clock):
    transport = HttpxTransport(transport=httpx.MockTransport(recorder))
    return create_app(make_config(admin_token="let-me-in"), transport=transport, clock=clock, start_scheduler=False)


def signed_headers(body, clock, **extra):
    ts = to_epoch(clock.now())
    return {"X-Relay-Signature": sign_payload(SOURCE_SECRET, body, ts), "X-Relay-Timestamp": str(ts), **extra}


def test_signed_webhook_is_accepted_and_delivered(app, recorder, clock):
    body = json.dumps({"id": "o-1", "total": 5}).encode()
    headers = signed_headers(body, clock, **{"Content-Type": "application/json", "X-Event-Type": "order.created"})
    response = app.test_client().post("/hooks/acme", data=body, headers=headers)
    assert response.status_code == 202
    payload = response.get_json()
    assert (payload["event"], payload["type"]) == ("o-1", "order.created")
    assert [d["target"] for d in payload["deliveries"]] == ["audit", "chat"]
    assert payload["deliveries"][0]["attempted_at"] == "2026-01-01T12:00:00Z"
    assert len(recorder.requests) == 2


def test_rejected_requests(app):
    client = app.test_client()
    body = b'{"id": "o-2"}'
    headers = {"X-Relay-Signature": "sha256=00", "Content-Type": "application/json"}
    response = client.post("/hooks/acme", data=body, headers=headers)
    assert response.status_code == 401 and "signature" in response.get_json()["error"]
    assert client.post("/hooks/nobody", data=body).status_code == 404
    response = client.post("/hooks/plain", data=b"{oops", headers={"Content-Type": "application/json"})
    assert response.status_code == 400


def test_status_page_requires_token_and_lists_targets(app):
    client = app.test_client()
    client.post("/hooks/plain", data=b'{"type": "order.paid"}', headers={"Content-Type": "application/json"})
    assert client.get("/admin/status").status_code == 403
    page = client.get("/admin/status", headers={"X-Admin-Token": "let-me-in"}).get_data(as_text=True)
    assert "webhookrelay 1.4.0" in page
    assert '<a href="/admin/status?target=audit">audit</a>' in page
    assert '<span class="badge ok"' in page
    assert "drop-pings (builtin)" in page
    filtered = client.get("/admin/status?target=chat&token=let-me-in").get_data(as_text=True)
    assert "Recent attempts for chat" in filtered


def test_status_json_uses_iso_timestamps(app):
    client = app.test_client()
    body = b'{"type": "order.paid", "id": "p1"}'
    client.post("/hooks/plain", data=body, headers={"Content-Type": "application/json"})
    status = client.get("/admin/status.json?token=let-me-in").get_json()
    assert status["now"] == "2026-01-01T12:00:00Z"
    assert status["started_at"] == "2026-01-01T12:00:00Z"
    assert status["received"] == 1
    assert status["recent"][0]["event"] == "p1" and status["recent"][0]["attempted_at"] == "2026-01-01T12:00:00Z"
    audit = next(row for row in status["targets"] if row["name"] == "audit")
    assert (audit["delivered"], audit["last_attempt_at"]) == (1, "2026-01-01T12:00:00Z")


def test_scheduler_starts_with_first_request(recorder, clock):
    transport = HttpxTransport(transport=httpx.MockTransport(recorder))
    app = create_app(make_config(), transport=transport, clock=clock)
    scheduler = app.extensions["webhookrelay"].dispatcher.scheduler
    try:
        app.test_client().get("/admin/status.json")
        assert scheduler.running
    finally:
        scheduler.stop()


def test_replay_archive_into_app(app, recorder):
    archive = [
        "# exported from production",
        json.dumps({"source": "plain", "headers": {"Content-Type": "application/json", "Content-Length": "99"},
                    "body": '{"type": "order.created", "id": "r1"}'}),
        "",
        json.dumps({"source": "plain", "headers": {"Content-Type": "text/plain"}, "body_b64": "aGVsbG8="}),
        json.dumps({"source": "acme", "headers": {}, "body": "{}"}),
    ]
    results = replay(app, load_archive(archive))
    assert [(r.status, r.deliveries) for r in results] == [(202, 2), (202, 1), (401, 0)]
    assert results[0].event_id == "r1" and len(results[1].event_id) == 16
    assert recorder.requests[-1].content.decode().count('"text": "hello"') == 1
