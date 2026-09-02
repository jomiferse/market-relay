"""FastAPI application factory.

Publishes the versioned consumer contract under `/v1` (tasks.md 5.1):
instrument search, listings, latest observation, observation ranges and
operational/data status, all requiring an authorized consumer identity
(`domain.governance.consumer_auth`). `/health` remains public and
database-free, as in wave 1 (tasks.md 1.2).

specs/consumer-api/spec.md § "Unauthenticated consumer" requires that an
authentication rejection not reveal data, configuration or the existence of
secrets; the unhandled exception handler applies the same principle to any
unexpected failure, sanitizing the message before logging it and always
returning a generic detail to the client.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from market_relay.api.routers import catalog, observations
from market_relay.api.routers import status as status_router
from market_relay.config import Settings, get_settings
from market_relay.domain.governance.consumer_auth import ConsumerAuthenticator, ConsumerCredential

logger = logging.getLogger("market_relay.api")

API_V1_PREFIX = "/v1"


def _build_consumer_credentials(settings: Settings) -> tuple[ConsumerCredential, ...]:
    return tuple(
        ConsumerCredential(
            consumer_id=entry.consumer_id, env_var=entry.env_var, scopes=entry.scopes
        )
        for entry in settings.consumer_credentials
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings if settings is not None else get_settings()
    app = FastAPI(
        title="MarketRelay",
        version="1.0.0",
        description=(
            "Governed catalog and EOD prices for Holdria. Does not offer "
            "real-time prices nor receive portfolios, positions or "
            "personal end-user credentials."
        ),
    )

    # State shared per request, built once per app: the database session
    # is opened lazily (see `api.deps.get_db`) so that `/health` never
    # touches the database or credentials.
    app.state.settings = settings
    app.state.consumer_authenticator = ConsumerAuthenticator(_build_consumer_credentials(settings))

    @app.get("/health", tags=["operations"])
    def health() -> dict[str, str]:
        return {
            "status": "ok",
            "service": settings.service_name,
            "environment": settings.environment,
        }

    app.include_router(catalog.router, prefix=API_V1_PREFIX)
    app.include_router(observations.router, prefix=API_V1_PREFIX)
    app.include_router(status_router.router, prefix=API_V1_PREFIX)

    @app.exception_handler(Exception)
    async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        # Neither the exception payload nor the request target is trusted.
        # Keep only generated, allowlisted diagnostic context.
        correlation_id = str(uuid.uuid4())
        logger.error(
            "Unhandled application error",
            extra={"error_code": "internal_error", "correlation_id": correlation_id},
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "Internal error."},
            headers={"X-Correlation-ID": correlation_id},
        )

    return app
