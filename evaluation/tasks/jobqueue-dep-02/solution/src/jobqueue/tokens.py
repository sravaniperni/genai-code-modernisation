"""Signed job tokens (JWT) granting a client access to a single job."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import jwt

from jobqueue import clock
from jobqueue.errors import TokenError, TokenExpired

SCOPES = frozenset({"status", "result", "cancel", "retry"})


@dataclass(frozen=True)
class TokenClaims:
    job_id: str
    scopes: frozenset[str]
    issued_at: datetime
    expires_at: datetime


class TokenSigner:
    """Issues and verifies HMAC-signed job tokens: ``sub`` is the job, ``scope`` the allowed operations."""

    def __init__(self, secret: str, *, issuer: str = "jobqueue", ttl: float = 3600.0, algorithm: str = "HS256",
                 leeway: float = 0.0):
        if not secret:
            raise ValueError("a signing secret is required")
        self.secret, self.issuer, self.ttl, self.algorithm, self.leeway = secret, issuer, ttl, algorithm, leeway

    def issue(self, job_id: str, scopes: Iterable[str] = ("status",), *, now: datetime | None = None) -> str:
        wanted = set(scopes)
        if not wanted or wanted - SCOPES:
            raise ValueError(f"scopes must be a non-empty subset of {sorted(SCOPES)}")
        issued = clock.ensure_utc(now) if now is not None else clock.utcnow()
        claims = {"sub": job_id, "iss": self.issuer, "scope": " ".join(sorted(wanted)), "iat": issued,
                  "exp": issued + timedelta(seconds=self.ttl)}
        return jwt.encode(claims, self.secret, algorithm=self.algorithm)

    def verify(self, token: str, *, scope: str | None = None) -> TokenClaims:
        """Check signature, issuer and expiry (and ``scope`` when given); raises :class:`TokenError`."""
        try:
            claims = jwt.decode(token, self.secret, algorithms=[self.algorithm], issuer=self.issuer,
                                leeway=self.leeway, options={"require": ["exp", "iat"]})
        except jwt.ExpiredSignatureError as exc:
            raise TokenExpired("job token has expired") from exc
        except jwt.InvalidTokenError as exc:
            raise TokenError(f"invalid job token: {exc}") from exc
        scopes = frozenset(str(claims.get("scope", "")).split())
        if not claims.get("sub"):
            raise TokenError("job token has no subject")
        if scope is not None and scope not in scopes:
            raise TokenError(f"job token does not grant {scope!r}")
        return TokenClaims(claims["sub"], scopes, clock.from_timestamp(claims["iat"]),
                           clock.from_timestamp(claims["exp"]))

    @staticmethod
    def peek(token: str) -> dict[str, Any]:
        """Return the claims without verifying anything (for logging and routing only)."""
        try:
            return jwt.decode(token, options={"verify_signature": False})
        except jwt.InvalidTokenError as exc:
            raise TokenError(f"malformed job token: {exc}") from exc
