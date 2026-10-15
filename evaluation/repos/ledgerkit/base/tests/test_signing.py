import pytest

from ledgerkit.errors import SignatureError
from ledgerkit.signing import read_unverified, sign_report, verify_report

KEY = "test-signing-key-0123456789abcdef"
REPORT = {"kind": "trial-balance", "total_debit": "12900.00", "total_credit": "12900.00"}


def test_sign_and_verify():
    token = sign_report(REPORT, KEY)
    assert isinstance(token, str) and token.count(".") == 2
    assert verify_report(token, KEY) == REPORT
    assert read_unverified(token)["iss"] == "ledgerkit"


def test_tampering_and_wrong_keys_are_detected():
    token = sign_report(REPORT, KEY)
    with pytest.raises(SignatureError):
        verify_report(token, "another-key-0123456789abcdefghij")
    header, payload, signature = token.split(".")
    with pytest.raises(SignatureError):
        verify_report(".".join([header, payload, signature[::-1]]), KEY)


def test_expired_reports_are_rejected():
    token = sign_report(REPORT, KEY, issued_at=1_000_000, ttl=60)
    with pytest.raises(SignatureError, match="expired"):
        verify_report(token, KEY)
