from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from modernisation.config import get_settings


@lru_cache(maxsize=4)
def get_engine(url: str | None = None) -> Engine:
    return create_engine(
        url or get_settings().database_url,
        pool_pre_ping=True,  # transparently replaces connections broken by a database restart
        pool_size=10,
        max_overflow=10,
        future=True,
    )


def session_factory(url: str | None = None) -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(url), expire_on_commit=False)


@contextmanager
def session_scope(url: str | None = None) -> Iterator[Session]:
    session = session_factory(url)()
    try:
        yield session
        session.commit()
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()
