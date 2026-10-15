import hashlib
import hmac
import json
from datetime import datetime, timezone

import httpx
import pytest

from webhookrelay.app import create_app
from webhookrelay.clock import FixedClock
from webhookrelay.transports import HttpxTransport

SECRET = "acme-staging-secret"
TS = 1767268800  # 2026-01-01T12:00:00Z


def signature(body, ts=TS, secret=SECRET):
    return "sha256=" + hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()


@pytest.fixture
def client():
    config = {
        "sources": {"acme": {"secret": SECRET}},
        "targets": {"ledger": {"url": "https://ledger.example/in"}},
        "rules": [{"targets": ["ledger"]}],
    }
    transport_requests = []

    def handler(request):
        request.read()
        transport_requests.append(request)
        return httpx.Response(200)

    app = create_app(config, transport=HttpxTransport(transport=httpx.MockTransport(handler)),
                     clock=FixedClock(datetime(2026, 1, 1, 12, tzinfo=timezone.utc)), start_scheduler=False)
    test_client = app.test_client()
    test_client.delivered = transport_requests
    return test_client


def post(client, body, sig=None, content_type="application/json"):
    headers = {"Content-Type": content_type, "X-Relay-Timestamp": str(TS),
               "X-Relay-Signature": sig if sig is not None else signature(body)}
    return client.post("/hooks/acme", data=body, headers=headers)


def test_reported_request_is_accepted(client):
    body = b'{"invoice":"INV-7","amount":1200}'
    response = post(client, body, "sha256=a4200650bc3fd4fc86d44cb41844b9afa07d54f7ab435cc956c6a2489858ab2d")
    assert response.status_code == 202
    assert len(client.delivered) == 1
    assert json.loads(client.delivered[0].content)["data"] == {"invoice": "INV-7", "amount": 1200}


@pytest.mark.parametrize(
    "body",
    [
        json.dumps({"type": "invoice.paid", "id": "inv-8", "lines": [1, 2]}, indent=2).encode() + b"\n",
        b'{"id":"inv-9","type":"invoice.paid","customer":{"name":"Zo\xc3\xab"}}',
        b'  {"type": "invoice.paid",   "id": "inv-10"}  ',
        json.dumps({"id": "inv-11", "type": "invoice.paid"}).encode(),
    ],
    ids=["pretty-trailing-newline", "compact-utf8", "extra-whitespace", "python-default"],
)
def test_any_formatting_with_a_valid_signature_is_accepted(client, body):
    response = post(client, body)
    assert response.status_code == 202, response.get_json()
    payload = response.get_json()
    assert payload["type"] == "invoice.paid" and payload["event"] == json.loads(body)["id"]


def test_json_with_charset_parameter(client):
    body = '{"id":"inv-12","type":"invoice.voided","memo":"Grüße"}'.encode()
    response = post(client, body, content_type="application/json; charset=utf-8")
    assert response.status_code == 202


def test_tampered_bodies_are_rejected(client):
    body = b'{"invoice":"INV-7","amount":1200}'
    sig = signature(body)
    assert post(client, b'{"invoice":"INV-7","amount":9200}', sig).status_code == 401
    assert post(client, b'{"invoice": "INV-7", "amount": 1200}', sig).status_code == 401
    assert post(client, body + b"\n", sig).status_code == 401
    reserialised = json.dumps(json.loads(body)).encode()
    response = post(client, body, signature(reserialised))
    assert response.status_code == 401 and response.get_json() == {"error": "signature mismatch"}
    assert client.delivered == []


def test_non_json_bodies_still_verify(client):
    body = b"invoice=INV-13&amount=50"
    assert post(client, body, content_type="application/x-www-form-urlencoded").status_code == 202
    assert post(client, body, signature(b"invoice=INV-13&amount=5"),
                content_type="application/x-www-form-urlencoded").status_code == 401
