import importlib.metadata
from datetime import datetime, timedelta, timezone

import jwt
import pytest

from jobqueue.errors import TokenError, TokenExpired
from jobqueue.tokens import TokenSigner

SECRET = "acceptance-secret"


def now():
    return datetime.now(timezone.utc).replace(microsecond=0)


def raw_token(claims, secret=SECRET):
    token = jwt.encode(claims, secret, algorithm="HS256")
    return token.decode("ascii") if isinstance(token, bytes) else token


def test_pyjwt_version_is_pinned():
    assert importlib.metadata.version("PyJWT") == "2.9.0"


def test_issue_returns_text_that_verifies():
    signer = TokenSigner(SECRET, ttl=900)
    issued = now()
    token = signer.issue("job-42", ["result", "status"], now=issued)
    assert isinstance(token, str) and token.count(".") == 2
    claims = signer.verify(token, scope="result")
    assert claims.job_id == "job-42" and claims.scopes == frozenset({"result", "status"})
    assert claims.issued_at == issued and claims.expires_at == issued + timedelta(seconds=900)
    assert claims.issued_at.utcoffset() == timedelta(0)
    standard = jwt.decode(token, SECRET, algorithms=["HS256"], issuer="jobqueue")
    assert standard["sub"] == "job-42" and standard["scope"] == "result status"


def test_expired_tokens_raise_token_expired():
    signer = TokenSigner(SECRET, ttl=60)
    with pytest.raises(TokenExpired):
        signer.verify(signer.issue("job-1", now=now() - timedelta(minutes=10)))
    lenient = TokenSigner(SECRET, ttl=60, leeway=3600)
    assert lenient.verify(signer.issue("job-1", now=now() - timedelta(minutes=10))).job_id == "job-1"


@pytest.mark.parametrize("missing", ["exp", "iat"])
def test_tokens_without_mandatory_claims_are_rejected(missing):
    claims = {"sub": "job-1", "iss": "jobqueue", "scope": "status", "iat": now(), "exp": now() + timedelta(hours=1)}
    del claims[missing]
    with pytest.raises(TokenError):
        TokenSigner(SECRET).verify(raw_token(claims))


def test_other_invalid_tokens_raise_token_error():
    signer = TokenSigner(SECRET)
    good = {"sub": "job-1", "scope": "status", "iat": now(), "exp": now() + timedelta(hours=1)}
    cases = [
        raw_token({**good, "iss": "someone-else"}),
        raw_token({**good, "iss": "jobqueue"}, secret="wrong-secret"),
        raw_token({**good, "iss": "jobqueue", "sub": ""}),
        signer.issue("job-1")[:-4] + "AAAA",
        "definitely.not.ajwt",
    ]
    for token in cases:
        with pytest.raises(TokenError):
            signer.verify(token)
    with pytest.raises(TokenError):
        signer.verify(signer.issue("job-1", ["status"]), scope="cancel")


def test_peek_does_not_verify():
    old_foreign = TokenSigner("other-key", issuer="partner").issue("job-7", ["cancel"], now=now() - timedelta(days=2))
    claims = TokenSigner.peek(old_foreign)
    assert (claims["sub"], claims["iss"], claims["scope"]) == ("job-7", "partner", "cancel")
    assert claims["exp"] < now().timestamp()
    with pytest.raises(TokenError):
        TokenSigner.peek("not-a-token")
