from __future__ import annotations

import hmac
from collections.abc import Iterator

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from modernisation.config import Settings, get_settings
from modernisation.db.session import session_factory


def get_session() -> Iterator[Session]:
    session = session_factory()()
    try:
        yield session
    finally:
        session.close()


def require_token(authorization: str | None = Header(default=None), settings: Settings = Depends(get_settings)) -> None:
    """Mutating endpoints require the API token when one is configured."""
    if settings.api_token is None:
        return
    expected = f"Bearer {settings.api_token.get_secret_value()}"
    if authorization is None or not hmac.compare_digest(authorization.encode(), expected.encode()):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing or invalid API token")
