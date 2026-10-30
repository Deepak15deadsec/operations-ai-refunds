"""Engine and session factories. Services receive a Session; transactions are explicit."""

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


@lru_cache
def get_engine(url: str | None = None) -> Engine:
    return create_engine(url or get_settings().database_url, pool_pre_ping=True, pool_size=10, max_overflow=5)


def session_factory(url: str | None = None) -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(url), expire_on_commit=False)


@contextmanager
def transaction(url: str | None = None) -> Iterator[Session]:
    """One unit of work: commit on success, roll back on any exception."""
    session = session_factory(url)()
    try:
        yield session
        session.commit()
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Iterator[Session]:
    """FastAPI dependency: request-scoped session, committed by the handler's service calls."""
    session = session_factory()()
    try:
        yield session
        session.commit()
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()


def allow_maintenance(session: Session) -> None:
    """Bypass append-only/immutability triggers for this transaction (seeding and test resets only)."""
    session.execute(text("SET LOCAL app.maintenance = 'on'"))
