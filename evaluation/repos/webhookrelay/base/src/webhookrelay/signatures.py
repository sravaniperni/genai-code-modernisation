"""Authentication of inbound webhooks (HMAC signatures, JWT bearer tokens) and outbound delivery tokens."""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any

import jwt

from .clock import SystemClock, from_epoch
from .config import Source
from .payloads import header_value

DEFAULT_TOLERANCE = 300
SIGNATURE_HEADERS = ("X-Relay-Signature", "X-Hub-Signature-256")


class SignatureError(Exception):
    """An inbound request failed authentication."""


def sign_payload(secret: str, body: bytes, timestamp: int | None = None) -> str:
    """Return the ``sha256=<hex>`` signature of ``body``.

    When ``timestamp`` is given the signed message is ``b"<timestamp>." + body``, which binds the
    signature to the time it was produced and lets receivers reject replays.
    """
    message = body if timestamp is None else f"{timestamp}.".encode() + body
    digest = hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def verify_hmac(secret: str, body: bytes, signature: str | None, timestamp: str | None = None, *,
                tolerance: int = DEFAULT_TOLERANCE, clock: Any = None) -> None:
    """Check ``signature`` for ``body`` (the exact bytes received); raise :class:`SignatureError` if invalid."""
    if not signature:
        raise SignatureError("missing signature")
    scheme, _, digest = signature.partition("=")
    if scheme != "sha256" or not digest:
        raise SignatureError("unsupported signature scheme")
    ts: int | None = None
    if timestamp is not None:
        try:
            ts = int(timestamp)
        except ValueError:
            raise SignatureError("invalid signature timestamp") from None
        now = (clock or SystemClock()).now()
        if abs((now - from_epoch(ts)).total_seconds()) > tolerance:
            raise SignatureError("signature timestamp outside tolerance")
    expected = sign_payload(secret, body, ts)
    if not hmac.compare_digest(expected.encode(), signature.strip().lower().encode()):
        raise SignatureError("signature mismatch")


def verify_jwt(token: str, issuers: Mapping[str, str], *, audience: str | None = None, leeway: int = 0) -> dict:
    """Verify an HS256 bearer token issued by one of ``issuers`` (issuer name -> shared secret)."""
    try:
        unverified = jwt.decode(token, verify=False)
    except jwt.InvalidTokenError as exc:
        raise SignatureError("malformed token") from exc
    issuer = unverified.get("iss")
    key = issuers.get(issuer) if isinstance(issuer, str) else None
    if key is None:
        raise SignatureError(f"unknown token issuer {issuer!r}")
    try:
        return jwt.decode(token, key, audience=audience, issuer=issuer, leeway=leeway)
    except jwt.ExpiredSignature as exc:
        raise SignatureError("token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise SignatureError(f"invalid token: {exc}") from exc


def issue_delivery_token(
    secret: str, *, issuer: str, audience: str, subject: str, issued_at: datetime, ttl: int = 300
) -> str:
    """Create the HS256 token sent as ``Authorization: Bearer`` with deliveries to ``auth: jwt`` targets."""
    expires = issued_at + timedelta(seconds=ttl)
    claims = {"iss": issuer, "aud": audience, "sub": subject, "iat": issued_at, "exp": expires}
    token = jwt.encode(claims, secret, algorithm="HS256")
    return token.decode("ascii")


def authenticate(source: Source, headers: Mapping[str, str], body: bytes, *, clock: Any = None) -> dict | None:
    """Authenticate an inbound request for ``source``; returns the token claims for JWT sources."""
    if source.secret:
        signature = next((v for v in (header_value(headers, h) for h in SIGNATURE_HEADERS) if v), None)
        timestamp = header_value(headers, "X-Relay-Timestamp")
        verify_hmac(source.secret, body, signature, timestamp, tolerance=source.tolerance, clock=clock)
        return None
    if source.jwt_issuers:
        scheme, _, token = (header_value(headers, "Authorization") or "").partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            raise SignatureError("missing bearer token")
        return verify_jwt(token.strip(), source.jwt_issuers, audience=source.audience)
    return None
