from datetime import datetime, timezone

import pytest
from conftest import SOURCE_SECRET, T0

from webhookrelay.clock import isoformat_z, to_epoch
from webhookrelay.config import Source
from webhookrelay.signatures import (
    SignatureError,
    authenticate,
    issue_delivery_token,
    sign_payload,
    verify_hmac,
    verify_jwt,
)

BODY = b'{"type": "order.created", "id": "evt-1"}'
FAR_FUTURE_TTL = 100 * 365 * 24 * 3600


def test_epoch_helpers_are_utc():
    assert to_epoch(T0) == 1767268800
    assert isoformat_z(datetime(2026, 1, 1, 13, 30, tzinfo=timezone.utc)) == "2026-01-01T13:30:00Z"


def test_hmac_roundtrip_with_timestamp(clock):
    ts = to_epoch(clock.now())
    signature = sign_payload(SOURCE_SECRET, BODY, ts)
    assert signature.startswith("sha256=")
    verify_hmac(SOURCE_SECRET, BODY, signature, str(ts), clock=clock)


def test_hmac_rejects_tampered_body_and_bad_scheme(clock):
    signature = sign_payload(SOURCE_SECRET, BODY)
    with pytest.raises(SignatureError, match="mismatch"):
        verify_hmac(SOURCE_SECRET, BODY + b" ", signature)
    with pytest.raises(SignatureError, match="scheme"):
        verify_hmac(SOURCE_SECRET, BODY, "md5=abc")
    with pytest.raises(SignatureError, match="missing"):
        verify_hmac(SOURCE_SECRET, BODY, None)


def test_hmac_timestamp_tolerance(clock):
    ts = to_epoch(clock.now()) - 600
    signature = sign_payload(SOURCE_SECRET, BODY, ts)
    with pytest.raises(SignatureError, match="tolerance"):
        verify_hmac(SOURCE_SECRET, BODY, signature, str(ts), tolerance=300, clock=clock)
    verify_hmac(SOURCE_SECRET, BODY, signature, str(ts), tolerance=900, clock=clock)


def test_jwt_roundtrip():
    issued = datetime(2020, 1, 1, tzinfo=timezone.utc)
    token = issue_delivery_token(
        SOURCE_SECRET, issuer="billing", audience="relay", subject="evt-9", issued_at=issued, ttl=FAR_FUTURE_TTL
    )
    assert isinstance(token, str) and token.count(".") == 2
    claims = verify_jwt(token, {"billing": SOURCE_SECRET}, audience="relay")
    assert claims["sub"] == "evt-9"
    assert claims["iss"] == "billing"


def test_jwt_rejects_expired_unknown_issuer_and_wrong_key():
    old = datetime(2001, 1, 1, tzinfo=timezone.utc)
    expired = issue_delivery_token(SOURCE_SECRET, issuer="billing", audience="relay", subject="s", issued_at=old)
    with pytest.raises(SignatureError, match="expired"):
        verify_jwt(expired, {"billing": SOURCE_SECRET}, audience="relay")
    issued = datetime(2020, 1, 1, tzinfo=timezone.utc)
    token = issue_delivery_token(
        SOURCE_SECRET, issuer="billing", audience="relay", subject="s", issued_at=issued, ttl=FAR_FUTURE_TTL
    )
    with pytest.raises(SignatureError, match="issuer"):
        verify_jwt(token, {"shipping": SOURCE_SECRET}, audience="relay")
    with pytest.raises(SignatureError):
        verify_jwt(token, {"billing": "another-secret-another-secret-12345"}, audience="relay")


def test_authenticate_hmac_source(clock):
    source = Source("acme", secret=SOURCE_SECRET)
    ts = to_epoch(clock.now())
    headers = {"X-Relay-Signature": sign_payload(SOURCE_SECRET, BODY, ts), "X-Relay-Timestamp": str(ts)}
    assert authenticate(source, headers, BODY, clock=clock) is None
    with pytest.raises(SignatureError):
        authenticate(source, {"X-Relay-Timestamp": str(ts)}, BODY, clock=clock)
    assert authenticate(Source("open"), {}, BODY) is None
