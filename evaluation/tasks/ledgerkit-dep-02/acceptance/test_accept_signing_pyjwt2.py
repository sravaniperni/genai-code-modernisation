import base64
import hashlib
import hmac
import importlib.metadata
import json

import pytest

from ledgerkit.errors import SignatureError
from ledgerkit.signing import read_unverified, sign_report, verify_report

KEY = "acceptance-signing-key-0123456789abcdef"
REPORT = {"kind": "trial-balance", "currency": "USD", "lines": [{"code": "1000", "debit": "10.00", "credit": "0"}]}
LEGACY_KEY = "legacy-signing-key-0123456789abcdef"
LEGACY_TOKEN = (
    "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJpc3MiOiJsZWRnZXJraXQiLCJpYXQiOjE3MDQwNjcyMDAsInJlcG9ydCI6eyJraW5kIjoidH"
    "JpYWwtYmFsYW5jZSIsImN1cnJlbmN5IjoiVVNEIiwidG90YWxfZGViaXQiOiI2MjM0LjUwIiwidG90YWxfY3JlZGl0IjoiNjIzNC41MCJ9fQ.Sth"
    "z4HE0VTuN5h5VgxjDWk7qaSeUkAgRFUk3FICq5G4"
)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _token(header: dict, claims: dict, key: str | None, digest=hashlib.sha256) -> str:
    signing_input = f"{_b64(json.dumps(header).encode())}.{_b64(json.dumps(claims).encode())}"
    signature = "" if key is None else _b64(hmac.new(key.encode(), signing_input.encode(), digest).digest())
    return f"{signing_input}.{signature}"


def test_pyjwt_is_pinned_to_2_10_1():
    assert importlib.metadata.version("PyJWT") == "2.10.1"


def test_round_trip_returns_text_token():
    token = sign_report(REPORT, KEY)
    assert isinstance(token, str) and token.count(".") == 2
    header = json.loads(base64.urlsafe_b64decode(token.split(".")[0] + "=="))
    assert header["alg"] == "HS256"
    assert verify_report(token, KEY) == REPORT


def test_claims_and_expiry():
    token = sign_report(REPORT, KEY, issued_at=1_700_000_000, ttl=3600)
    claims = read_unverified(token)
    assert claims == {"iss": "ledgerkit", "iat": 1_700_000_000, "exp": 1_700_003_600, "report": REPORT}
    with pytest.raises(SignatureError, match="expired"):
        verify_report(token, KEY)
    fresh = sign_report(REPORT, KEY, ttl=3600)
    assert verify_report(fresh, KEY) == REPORT


def test_tampering_wrong_key_and_issuer_are_rejected():
    token = sign_report(REPORT, KEY)
    header, payload, signature = token.split(".")
    forged = json.loads(base64.urlsafe_b64decode(payload + "=="))
    forged["report"]["currency"] = "EUR"
    with pytest.raises(SignatureError):
        verify_report(".".join([header, _b64(json.dumps(forged).encode()), signature]), KEY)
    with pytest.raises(SignatureError):
        verify_report(token, "a-completely-different-key-0123456789")
    other_issuer = _token({"alg": "HS256", "typ": "JWT"}, {"iss": "mallory", "iat": 1_700_000_000, "report": REPORT}, KEY)
    with pytest.raises(SignatureError):
        verify_report(other_issuer, KEY)


def test_only_hs256_is_accepted():
    claims = {"iss": "ledgerkit", "iat": 1_700_000_000, "report": REPORT}
    good = _token({"alg": "HS256", "typ": "JWT"}, claims, KEY)
    assert verify_report(good, KEY) == REPORT
    with pytest.raises(SignatureError):
        verify_report(_token({"alg": "none", "typ": "JWT"}, claims, None), KEY)
    with pytest.raises(SignatureError):
        verify_report(_token({"alg": "HS512", "typ": "JWT"}, claims, KEY, hashlib.sha512), KEY)


def test_tokens_from_previous_release_still_verify():
    report = verify_report(LEGACY_TOKEN, LEGACY_KEY)
    assert report == {"kind": "trial-balance", "currency": "USD", "total_debit": "6234.50", "total_credit": "6234.50"}
    assert read_unverified(LEGACY_TOKEN)["iat"] == 1704067200


def test_read_unverified_rejects_garbage_and_ignores_signature():
    token = sign_report(REPORT, KEY, issued_at=1_000, ttl=1)
    assert read_unverified(token)["report"] == REPORT
    with pytest.raises(SignatureError):
        read_unverified("definitely-not-a-token")
