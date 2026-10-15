"""Tamper-evident report exports: reports are signed as HS256 JSON Web Tokens."""

from __future__ import annotations

import time
from typing import Any

import jwt

from ledgerkit.errors import SignatureError

ALGORITHM = "HS256"
ISSUER = "ledgerkit"


def sign_report(report: dict[str, Any], key: str, *, issued_at: int | None = None, ttl: int | None = None) -> str:
    """Sign a JSON-compatible report; returns the compact token as text."""
    claims: dict[str, Any] = {"iss": ISSUER, "iat": int(time.time()) if issued_at is None else issued_at,
                              "report": report}
    if ttl is not None:
        claims["exp"] = claims["iat"] + ttl
    return jwt.encode(claims, key, algorithm=ALGORITHM)


def verify_report(token: str, key: str) -> dict[str, Any]:
    """Return the report inside ``token`` after checking signature, issuer and expiry."""
    try:
        claims = jwt.decode(token, key, algorithms=[ALGORITHM], issuer=ISSUER)
    except jwt.ExpiredSignatureError as exc:
        raise SignatureError("signed report has expired") from exc
    except jwt.InvalidTokenError as exc:
        raise SignatureError(f"invalid signed report: {exc}") from exc
    return claims["report"]


def read_unverified(token: str) -> dict[str, Any]:
    """All claims of ``token`` without checking the signature -- for display purposes only."""
    try:
        return jwt.decode(token, options={"verify_signature": False})
    except jwt.InvalidTokenError as exc:
        raise SignatureError(f"malformed signed report: {exc}") from exc
