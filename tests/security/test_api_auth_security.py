"""Consumer API security (tasks.md 5.2, 5.4).

`specs/consumer-api/spec.md` § "Unauthenticated consumer" requires that a
rejection reveal no data, configuration, or existence of secrets.
`specs/source-governance/spec.md` § "Credential protection" requires that
no log, error, or response include a secret. This module tests both
principles against the real HTTP API, with a deterministic decoy never
used as a real credential.
"""

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from market_relay.domain.catalog.service import CatalogService
from tests.conftest import HOLDRIA_DECOY_API_KEY
from tests.factories import create_equity_listing

_PROTECTED_PATH = "/v1/instruments/search"


def _auth(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"}


def test_missing_authorization_header_returns_generic_401(api_client: TestClient) -> None:
    response = api_client.get(_PROTECTED_PATH)

    assert response.status_code == 401
    assert response.json() == {"detail": "Not authenticated."}
    assert "www-authenticate" in {k.lower() for k in response.headers}


def test_malformed_authorization_header_is_rejected_like_a_missing_one(
    api_client: TestClient, holdria_api_key: str
) -> None:
    response = api_client.get(_PROTECTED_PATH, headers={"Authorization": holdria_api_key})

    assert response.status_code == 401
    assert response.json() == {"detail": "Not authenticated."}


def test_wrong_api_key_never_reveals_the_configured_decoy_secret(
    api_client: TestClient, holdria_api_key: str
) -> None:
    response = api_client.get(_PROTECTED_PATH, headers=_auth("wrong-value-entirely"))

    assert response.status_code == 401
    assert HOLDRIA_DECOY_API_KEY not in response.text
    assert "holdria" not in response.text.lower()


def test_unconfigured_consumer_credential_behaves_as_invalid_not_as_a_distinct_error(
    api_client: TestClient, api_settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A consumer registered in `Settings` whose environment variable was
    never set (e.g. disabled in this deployment) SHALL produce the same
    generic 401 as any other invalid credential.
    """

    monkeypatch.delenv("MARKET_RELAY_CONSUMER_CATALOG_ONLY_API_KEY", raising=False)

    response = api_client.get(_PROTECTED_PATH, headers=_auth("anything"))

    assert response.status_code == 401
    assert response.json() == {"detail": "Not authenticated."}


def test_forbidden_response_never_leaks_the_scopes_the_consumer_actually_has(
    api_client: TestClient, catalog_only_api_key: str
) -> None:
    response = api_client.get("/v1/status/operations", headers=_auth(catalog_only_api_key))

    assert response.status_code == 403
    assert response.json() == {"detail": "Access denied."}
    assert "catalog:read" not in response.text
    assert "operations:read" not in response.text


def test_not_found_response_never_leaks_internal_identifiers_beyond_the_requested_one(
    api_client: TestClient, holdria_api_key: str
) -> None:
    response = api_client.get(
        "/v1/listings/00000000-0000-0000-0000-000000000000", headers=_auth(holdria_api_key)
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Listing not found."}


def test_unhandled_exception_returns_generic_500_without_leaking_the_exception_message(
    api_client: TestClient, holdria_api_key: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unexpected failure never returns `str(exc)` to the client
    (specs/source-governance/spec.md § "Credential protection": no
    error SHALL include a secret, let alone the raw internal detail).
    """

    internal_detail = "simulated internal failure that must never reach the client"

    def _boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError(internal_detail)

    monkeypatch.setattr(CatalogService, "find_listings", _boom)

    # `raise_server_exceptions=False`: same as in
    # `tests/security/test_credentials.py`, so `TestClient` returns the
    # global handler's real HTTP response instead of re-raising the
    # exception in the test itself.
    client = TestClient(api_client.app, raise_server_exceptions=False)
    response = client.get(_PROTECTED_PATH, headers=_auth(holdria_api_key))

    assert response.status_code == 500
    assert response.json() == {"detail": "Internal error."}
    assert internal_detail not in response.text


@pytest.mark.parametrize(
    "exception_payload",
    [
        "opaque-random-token-4be988adf7414ce8a3cf",
        "api_key=decoy-api-key-value",
        "postgresql://user:decoy-password@database.invalid/app",
        "ordinary harmless diagnostic text",
    ],
)
def test_unhandled_exception_log_never_includes_exception_payload(
    api_client: TestClient,
    holdria_api_key: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    exception_payload: str,
) -> None:
    def _boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError(exception_payload)

    monkeypatch.setattr(CatalogService, "find_listings", _boom)

    client = TestClient(api_client.app, raise_server_exceptions=False)
    with caplog.at_level(logging.ERROR, logger="market_relay.api"):
        response = client.get(_PROTECTED_PATH, headers=_auth(holdria_api_key))

    assert response.status_code == 500
    assert exception_payload not in response.text
    assert response.headers["X-Correlation-ID"]
    for record in caplog.records:
        assert exception_payload not in record.getMessage()
        assert record.getMessage() == "Unhandled application error"


def test_valid_credential_is_never_echoed_back_in_any_successful_response(
    api_client: TestClient, db_session: Session, holdria_api_key: str
) -> None:
    create_equity_listing(db_session)

    response = api_client.get(_PROTECTED_PATH, headers=_auth(holdria_api_key))

    assert response.status_code == 200
    assert holdria_api_key not in response.text
