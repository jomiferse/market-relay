"""Shared dependencies for the consumer API (tasks.md 5.1-5.2).

Every non-public HTTP handler requires a `ConsumerIdentity` resolved by
`require_scope`. `specs/consumer-api/spec.md` § "Versioned and authenticated
API" forbids revealing data, configuration or the existence of secrets on
a rejection, so every failure variant here collapses to the same generic
codes and messages, regardless of the actual cause (missing header, unknown
credential or insufficient scope).
"""

from __future__ import annotations

from collections.abc import Callable, Iterator

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import APIKeyHeader
from sqlalchemy.orm import Session, sessionmaker

from market_relay.config import Settings
from market_relay.db.session import build_session_factory, create_engine_from_settings
from market_relay.domain.governance.consumer_auth import (
    ConsumerAuthenticationError,
    ConsumerAuthenticator,
    ConsumerAuthorizationError,
    ConsumerIdentity,
)

# `auto_error=False`: a missing header is treated the same as an invalid
# credential (same generic 401), never as a distinct schema error.
_AUTHORIZATION_HEADER = APIKeyHeader(name="Authorization", auto_error=False)
_BEARER_PREFIX = "Bearer "


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings  # type: ignore[no-any-return]


def get_db(request: Request) -> Iterator[Session]:
    """Per-request database session.

    The session factory is built lazily and cached on `app.state`: this way,
    an endpoint that never touches the database (e.g. `/health`) does not
    create an engine or open a SQLite file by default.
    """

    factory: sessionmaker[Session] | None = getattr(request.app.state, "session_factory", None)
    if factory is None:
        settings = get_settings_dep(request)
        engine = create_engine_from_settings(settings)
        factory = build_session_factory(engine)
        request.app.state.session_factory = factory

    session = factory()
    try:
        yield session
    finally:
        session.close()


def get_authenticator(request: Request) -> ConsumerAuthenticator:
    return request.app.state.consumer_authenticator  # type: ignore[no-any-return]


def _extract_bearer_token(header_value: str | None) -> str | None:
    if header_value is None or not header_value.startswith(_BEARER_PREFIX):
        return None
    return header_value[len(_BEARER_PREFIX) :]


def require_scope(scope: str) -> Callable[..., ConsumerIdentity]:
    """Builds a FastAPI dependency that requires an authenticated consumer
    with `scope` among its authorized scopes.
    """

    def _dependency(
        authorization: str | None = Depends(_AUTHORIZATION_HEADER),
        authenticator: ConsumerAuthenticator = Depends(get_authenticator),
    ) -> ConsumerIdentity:
        presented = _extract_bearer_token(authorization)
        try:
            identity = authenticator.authenticate(presented)
            authenticator.authorize(identity, scope)
        except ConsumerAuthenticationError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Not authenticated.",
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc
        except ConsumerAuthorizationError as exc:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied.",
            ) from exc
        return identity

    return _dependency
