from datetime import timedelta

import pytest

from jobqueue.clock import utcnow
from jobqueue.errors import TokenError, TokenExpired
from jobqueue.tokens import TokenSigner


@pytest.fixture
def signer():
    return TokenSigner("test-secret", ttl=600)


def test_issue_and_verify(signer):
    issued = utcnow().replace(microsecond=0)
    token = signer.issue("job-1", ["status", "cancel"], now=issued)
    assert isinstance(token, str) and token.count(".") == 2
    claims = signer.verify(token, scope="cancel")
    assert (claims.job_id, claims.scopes) == ("job-1", frozenset({"status", "cancel"}))
    assert claims.issued_at == issued and claims.expires_at == issued + timedelta(seconds=600)


def test_expired_tokens_are_rejected(signer):
    token = signer.issue("job-1", now=utcnow() - timedelta(hours=1))
    with pytest.raises(TokenExpired):
        signer.verify(token)


def test_foreign_or_out_of_scope_tokens_are_rejected(signer):
    foreign = TokenSigner("another-secret").issue("job-1")
    with pytest.raises(TokenError):
        signer.verify(foreign)
    with pytest.raises(TokenError):
        signer.verify(signer.issue("job-1", ["status"]), scope="cancel")
    with pytest.raises(TokenError):
        signer.verify("not-a-token")
    with pytest.raises(ValueError):
        signer.issue("job-1", ["delete"])


def test_peek_reads_claims_without_verifying(signer):
    token = TokenSigner("another-secret", issuer="elsewhere").issue("job-9", now=utcnow() - timedelta(days=1))
    claims = TokenSigner.peek(token)
    assert (claims["sub"], claims["iss"], claims["scope"]) == ("job-9", "elsewhere", "status")
    with pytest.raises(TokenError):
        TokenSigner.peek("garbage")
