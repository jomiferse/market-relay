"""Contract tests representing Holdria (tasks.md 5.4).

`specs/consumer-api/spec.md` § "Isolation of responsibilities" requires
that the API MUST NOT receive portfolios, positions, or personal
credentials from Holdria users, and MUST NOT assert real-time prices. This
module exercises the full contract from Holdria's perspective: search,
detail, latest observation and range, checking on each response the
effective date, currency, EOD nature, provenance, required attribution,
and status — with no Holdria request needing to send, and no response
needing to contain, portfolio, position, or end-customer data.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from datetime import date
from typing import Any

from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy.orm import Session

from market_relay.api import schemas
from market_relay.api.routers import catalog as catalog_router
from market_relay.api.routers import observations as observations_router
from market_relay.api.routers import status as status_router
from market_relay.domain.governance.models import PolicyCapability
from tests.factories import (
    approve_publication,
    create_equity_listing,
    deny_capability,
    record_observation,
)

_PORTFOLIO_TERMS = (
    "portfolio",
    "cartera",  # language-scan: intentional-spanish-value
    "position",
    "posicion",  # language-scan: intentional-spanish-value
    "posición",  # language-scan: intentional-spanish-value
    "holding",
    "customer",
)


def _auth(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"}


def test_no_route_accepts_a_portfolio_position_or_customer_parameter() -> None:
    """Inspects the real HTTP handler signatures: none declares a
    parameter suggesting portfolio, position, or end-customer data. This
    proves the absence structurally, not just by naming convention on a
    handful of example requests.
    """

    handlers: list[Callable[..., Any]] = [
        catalog_router.search_instruments,
        catalog_router.get_listing,
        observations_router.latest_observation,
        observations_router.observation_range,
        status_router.operational_status,
        status_router.data_status,
    ]
    for handler in handlers:
        parameter_names = set(inspect.signature(handler).parameters)
        for term in _PORTFOLIO_TERMS:
            assert not any(term in name.lower() for name in parameter_names), (
                f"{handler.__qualname__} declares a parameter related to '{term}'"
            )


def test_no_response_schema_exposes_a_portfolio_position_or_customer_field() -> None:
    """None of the published response models declares a portfolio,
    position, or end-customer field.
    """

    response_models: list[type[BaseModel]] = [
        schemas.InstrumentOut,
        schemas.ListingOut,
        schemas.InstrumentSearchResponse,
        schemas.ObservationValueOut,
        schemas.ObservationOut,
        schemas.ObservationRangeResponse,
        schemas.DataStatusOut,
        schemas.OperationalStatusOut,
        schemas.ErrorResponse,
    ]
    for model in response_models:
        field_names = set(model.model_fields)
        for term in _PORTFOLIO_TERMS:
            assert not any(term in name.lower() for name in field_names), (
                f"{model.__name__} declares a field related to '{term}'"
            )


def test_holdria_search_request_needs_only_public_instrument_criteria(
    api_client: TestClient, db_session: Session, holdria_api_key: str
) -> None:
    """Holdria locates a listing using public market criteria
    (ISIN, market, currency): none of them identifies a Holdria end user
    nor a position in their portfolio.
    """

    listing = create_equity_listing(db_session)

    response = api_client.get(
        "/v1/instruments/search",
        params={"isin": "DE0007164600", "mic": "XETR", "currency": "EUR"},
        headers=_auth(holdria_api_key),
    )

    assert response.status_code == 200
    result = response.json()["results"][0]
    assert result["listing_id"] == str(listing.id)


def test_holdria_observation_response_carries_effective_date_currency_provenance_and_status(
    api_client: TestClient, db_session: Session, holdria_api_key: str
) -> None:
    """Walks through the full tasks.md 5.4 scenario: effective date,
    currency, provenance, attribution, status and EOD semantics, without
    sending any portfolio data.
    """

    listing = create_equity_listing(db_session)
    approve_publication(db_session, "fake", attribute=True)
    session_date = date(2026, 1, 5)
    record_observation(db_session, listing, session_date=session_date, close="87.65")

    response = api_client.get(
        f"/v1/listings/{listing.id}/observations",
        params={"start": session_date.isoformat(), "end": session_date.isoformat()},
        headers=_auth(holdria_api_key),
    )

    assert response.status_code == 200
    observation = response.json()["observations"][0]

    # Effective date and EOD nature, never real-time
    # (specs/consumer-api/spec.md § "EOD price request").
    assert observation["session_date"] == session_date.isoformat()
    assert observation["availability"] == "OK"
    value = observation["value"]
    assert value["is_eod"] is True
    assert value["observation_type"] == "EOD_CLOSE"

    # Currency and raw close, never substituted by adjusted_close
    # (specs/market-observations/spec.md § "Raw value with no implicit adjustments").
    assert value["currency"] == "EUR"
    assert value["close"] == "87.65000000"

    # Provenance and required attribution
    # (specs/source-governance/spec.md § "Approved source requiring attribution").
    assert value["source"] == "fake"
    assert value["requires_attribution"] is True
    assert value["attribution"]

    # Deterministic selection exposed: revision and absence of discrepancy.
    assert value["revision"] == 1
    assert value["has_discrepancy"] is False


def test_holdria_never_receives_denied_data_even_when_it_was_previously_stored(
    api_client: TestClient, db_session: Session, holdria_api_key: str
) -> None:
    """specs/consumer-api/spec.md § 'Stored data not redistributable': the
    unavailability status is non-sensitive, it never reveals the stored
    value nor the reason for denial.
    """

    listing = create_equity_listing(db_session)
    approve_publication(db_session, "fake")
    deny_capability(db_session, "fake", PolicyCapability.REDISTRIBUTE)
    session_date = date(2026, 1, 5)
    record_observation(db_session, listing, session_date=session_date, close="555.55")

    response = api_client.get(
        f"/v1/listings/{listing.id}/observations",
        params={"start": session_date.isoformat(), "end": session_date.isoformat()},
        headers=_auth(holdria_api_key),
    )

    body = response.json()
    assert "555.55" not in response.text
    observation = body["observations"][0]
    assert observation["availability"] == "UNAVAILABLE"
    assert observation["value"] is None
