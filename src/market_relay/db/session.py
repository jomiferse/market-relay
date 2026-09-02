"""SQLAlchemy engine and session factories."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from market_relay.config import Settings


def create_engine_from_settings(settings: Settings) -> Engine:
    """Creates the `Engine` applying dialect-specific settings.

    SQLite needs `check_same_thread=False` for concurrent use in tests, and
    `foreign_keys=ON` via event is not necessary here because the
    migrations already declare the constraints; we keep `future=True`
    implicit in SQLAlchemy 2.
    """

    connect_args: dict[str, object] = {}
    if settings.is_sqlite:
        connect_args["check_same_thread"] = False

    return create_engine(settings.database_url, connect_args=connect_args)


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@contextmanager
def session_scope(
    session_factory: sessionmaker[Session],
) -> Generator[Session, None, None]:
    """Transactional context: commits on successful exit, rolls back on failure."""

    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
