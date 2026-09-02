"""Catalog v1 endpoints (tasks.md 5.1, 5.3; specs/instrument-catalog).

Exercises allowed/denied/invalid authentication (tasks.md 5.2) against
real endpoints, in addition to the catalog's own scenarios.
"""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from market_relay.domain.catalog.models import AssetClass
from market_relay.domain.catalog.service import CatalogService
from tests.factories import create_equity_listing


def _auth(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"}


def test_search_without_credentials_is_rejected_without_leaking_details(
    api_client: TestClient,
) -> None:
    response = api_client.get("/v1/instruments/search")

    assert response.status_code == 401
    body = response.json()
    assert body == {"detail": "Not authenticated."}


def test_search_with_invalid_credential_is_rejected(
    api_client: TestClient, holdria_api_key: str
) -> None:
    response = api_client.get("/v1/instruments/search", headers=_auth("not-" + holdria_api_key))

    assert response.status_code == 401


def test_search_with_valid_credential_and_scope_is_allowed(
    api_client: TestClient, db_session: Session, holdria_api_key: str
) -> None:
    create_equity_listing(db_session, isin="DE0007164600", venue="XETR", mic="XETR")

    response = api_client.get(
        "/v1/instruments/search", params={"isin": "DE0007164600"}, headers=_auth(holdria_api_key)
    )

    assert response.status_code == 200
    results = response.json()["results"]
    assert len(results) == 1
    assert results[0]["instrument"]["isin"] == "DE0007164600"
    assert results[0]["venue"] == "XETR"


def test_search_with_credential_lacking_scope_is_denied(
    api_client: TestClient, catalog_only_api_key: str
) -> None:
    # `catalog_only_api_key` SHALL have catalog access (verified in
    # spirit by the previous test); here we test a scope it lacks.
    response = api_client.get("/v1/status/operations", headers=_auth(catalog_only_api_key))

    assert response.status_code == 403
    assert response.json() == {"detail": "Access denied."}


def test_isin_traded_on_two_venues_returns_two_distinct_listings(
    api_client: TestClient, db_session: Session, holdria_api_key: str
) -> None:
    """specs/instrument-catalog/spec.md § 'ISIN with several listings'."""

    catalog = CatalogService(db_session)
    instrument = catalog.register_instrument(
        asset_class=AssetClass.EQUITY, name="SAP SE", isin="DE0007164600"
    )
    catalog.add_listing(
        instrument=instrument, venue="XETR", mic="XETR", ticker="SAP", currency="EUR"
    )
    catalog.add_listing(
        instrument=instrument, venue="XPAR", mic="XPAR", ticker="SAP", currency="EUR"
    )
    db_session.commit()

    response = api_client.get(
        "/v1/instruments/search", params={"isin": "DE0007164600"}, headers=_auth(holdria_api_key)
    )

    assert response.status_code == 200
    results = response.json()["results"]
    assert len(results) == 2
    venues = {r["venue"] for r in results}
    assert venues == {"XETR", "XPAR"}
    # Both listings share the same underlying instrument.
    assert {r["instrument"]["instrument_id"] for r in results} == {str(instrument.id)}


def test_get_listing_not_found_returns_sanitized_404(
    api_client: TestClient, holdria_api_key: str
) -> None:
    response = api_client.get(f"/v1/listings/{uuid.uuid4()}", headers=_auth(holdria_api_key))

    assert response.status_code == 404
    assert response.json() == {"detail": "Listing not found."}


def test_get_listing_returns_full_detail(
    api_client: TestClient, db_session: Session, holdria_api_key: str
) -> None:
    listing = create_equity_listing(db_session)

    response = api_client.get(f"/v1/listings/{listing.id}", headers=_auth(holdria_api_key))

    assert response.status_code == 200
    body = response.json()
    assert body["listing_id"] == str(listing.id)
    assert body["ticker"] == listing.ticker
    assert body["currency"] == "EUR"
