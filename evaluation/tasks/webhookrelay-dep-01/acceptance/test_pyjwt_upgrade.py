import importlib.metadata
from datetime import datetime, timezone

import httpx
import jwt
import pytest

from webhookrelay.app import create_app
from webhookrelay.clock import FixedClock
from webhookrelay.config import load_config
from webhookrelay.delivery import Dispatcher
from webhookrelay.payloads import Event
from webhookrelay.signatures import SignatureError, issue_delivery_token, verify_jwt
from webhookrelay.transports import HttpxTransport

SECRET = "issuer-secret-5c1f0e9d8b7a6c5d4e3f2a1b0c9d8e7f"
NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
PAST = 1577836800  # 2020-01-01
FUTURE = 4102444800  # 2100-01-01


def mint(claims, key=SECRET, algorithm="HS256", **kwargs):
    token = jwt.encode(claims, key, algorithm=algorithm, **kwargs)
    return token.decode() if isinstance(token, bytes) else token


def valid_claims(**overrides):
    claims = {"iss": "billing", "aud": "relay", "sub": "evt-1", "iat": PAST, "exp": FUTURE}
    claims.update(overrides)
    return claims


def test_pyjwt_version_is_pinned():
    assert importlib.metadata.version("PyJWT") == "2.10.1"


def test_issued_delivery_tokens_are_text_and_verifiable():
    issued = datetime(2020, 1, 1, tzinfo=timezone.utc)
    token = issue_delivery_token(SECRET, issuer="webhookrelay", audience="crm", subject="d-1", issued_at=issued, ttl=60)
    assert isinstance(token, str)
    header = jwt.get_unverified_header(token)
    assert header["alg"] == "HS256"
    claims = jwt.decode(token, SECRET, algorithms=["HS256"], audience="crm", options={"verify_exp": False})
    assert claims["iss"] == "webhookrelay" and claims["sub"] == "d-1"
    assert claims["iat"] == PAST and claims["exp"] == PAST + 60


def test_inbound_token_is_verified():
    claims = verify_jwt(mint(valid_claims()), {"billing": SECRET}, audience="relay")
    assert claims["sub"] == "evt-1" and claims["iss"] == "billing"


@pytest.mark.parametrize(
    "token, match",
    [
        (lambda: mint(valid_claims(exp=PAST + 60)), "expired"),
        (lambda: mint(valid_claims(iss="shipping")), "issuer"),
        (lambda: mint(valid_claims(), key="some-other-secret-0123456789abcdef"), None),
        (lambda: mint(valid_claims(aud="someone-else")), None),
        (lambda: mint(valid_claims(), key=None, algorithm="none"), None),
        (lambda: "not.a.token", None),
        (lambda: "garbage", None),
    ],
    ids=["expired", "unknown-issuer", "wrong-key", "wrong-audience", "alg-none", "bad-segments", "garbage"],
)
def test_bad_tokens_are_rejected(token, match):
    with pytest.raises(SignatureError, match=match):
        verify_jwt(token(), {"billing": SECRET}, audience="relay")


def test_jwt_target_deliveries_carry_a_valid_token():
    seen = []

    def handler(request):
        seen.append(request.headers["authorization"])
        return httpx.Response(202)

    config = load_config({
        "targets": {"crm": {"url": "https://crm.example/in", "auth": "jwt", "secret": SECRET}},
        "rules": [{"targets": ["crm"]}],
    })
    dispatcher = Dispatcher(config, transport=HttpxTransport(transport=httpx.MockTransport(handler)),
                            clock=FixedClock(NOW))
    [record] = dispatcher.dispatch(Event("shop", "order.created", "o-1", {}, NOW, {}))
    assert record.status == 202
    scheme, token = seen[0].split(" ", 1)
    assert scheme == "Bearer"
    claims = jwt.decode(token, SECRET, algorithms=["HS256"], audience="crm", options={"verify_exp": False})
    assert claims["sub"] == record.delivery_id
    assert claims["exp"] - claims["iat"] == 300
    assert verify_jwt(token, {"webhookrelay": SECRET}, audience="crm", leeway=10**10)["sub"] == record.delivery_id


def test_bearer_authenticated_endpoint():
    config = {
        "sources": {"billing": {"jwt_issuers": {"billing": SECRET}, "audience": "relay"}},
        "targets": {"audit": {"url": "https://audit.example/in"}},
        "rules": [{"targets": ["audit"]}],
    }
    transport = HttpxTransport(transport=httpx.MockTransport(lambda request: httpx.Response(200)))
    client = create_app(config, transport=transport, clock=FixedClock(NOW), start_scheduler=False).test_client()
    body = b'{"type": "invoice.paid", "id": "inv-1"}'
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {mint(valid_claims())}"}
    response = client.post("/hooks/billing", data=body, headers=headers)
    assert response.status_code == 202
    assert response.get_json()["event"] == "inv-1"
    expired = {"Content-Type": "application/json", "Authorization": f"Bearer {mint(valid_claims(exp=PAST))}"}
    response = client.post("/hooks/billing", data=body, headers=expired)
    assert response.status_code == 401 and "expired" in response.get_json()["error"]
    assert client.post("/hooks/billing", data=body, headers={"Content-Type": "application/json"}).status_code == 401
