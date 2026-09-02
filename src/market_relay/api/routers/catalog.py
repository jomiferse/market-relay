"""Catalog v1 endpoints: instrument search and listing detail.

tasks.md 5.1 and 5.3; `specs/instrument-catalog/spec.md`;
`specs/consumer-api/spec.md` § "Catalog and observation queries". The
catalog never receives nor requires Holdria's portfolios, positions or
personal credentials (specs/consumer-api/spec.md § "Separation of
concerns"): only public instrument search criteria.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from market_relay.api.deps import get_db, require_scope
from market_relay.api.schemas import ErrorResponse, InstrumentSearchResponse, ListingOut
from market_relay.domain.catalog.models import AssetClass
from market_relay.domain.catalog.service import CatalogService, ListingSearchCriteria
from market_relay.domain.governance.consumer_auth import ConsumerIdentity

CATALOG_READ_SCOPE = "catalog:read"

router = APIRouter(tags=["catalog"])

_AUTH_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "Missing or invalid credential."},
    403: {"model": ErrorResponse, "description": "Consumer without the required scope."},
}


@router.get(
    "/instruments/search",
    response_model=InstrumentSearchResponse,
    responses=_AUTH_RESPONSES,
    summary="Search listings by identifier, market or currency",
)
def search_instruments(
    isin: str | None = Query(default=None, description="ISIN of the economic instrument."),
    figi: str | None = Query(default=None, description="FIGI of the economic instrument."),
    ticker: str | None = Query(default=None, description="Ticker of the listing."),
    mic: str | None = Query(default=None, description="MIC (ISO 10383) of the market."),
    venue: str | None = Query(default=None, description="Listing venue."),
    currency: str | None = Query(default=None, description="ISO-4217 currency of the listing."),
    asset_class: AssetClass | None = Query(default=None, description="Asset class."),
    session: Session = Depends(get_db),
    _identity: ConsumerIdentity = Depends(require_scope(CATALOG_READ_SCOPE)),
) -> InstrumentSearchResponse:
    """Returns every listing that matches the given criteria.

    Does not resolve ambiguity: the same ISIN traded on several markets
    returns one entry per listing, each with its own `mic`/`venue`/
    `currency` (specs/instrument-catalog/spec.md § "ISIN with several
    listings").
    """

    catalog = CatalogService(session)
    criteria = ListingSearchCriteria(
        isin=isin,
        figi=figi,
        ticker=ticker,
        mic=mic,
        venue=venue,
        currency=currency,
        asset_class=asset_class,
    )
    listings = catalog.find_listings(criteria)
    results = [ListingOut.from_model(listing) for listing in listings]
    return InstrumentSearchResponse(results=results)


_LISTING_RESPONSES: dict[int | str, dict[str, Any]] = {
    **_AUTH_RESPONSES,
    404: {"model": ErrorResponse, "description": "Listing does not exist."},
}


@router.get(
    "/listings/{listing_id}",
    response_model=ListingOut,
    responses=_LISTING_RESPONSES,
    summary="Detail of a listing",
)
def get_listing(
    listing_id: uuid.UUID,
    session: Session = Depends(get_db),
    _identity: ConsumerIdentity = Depends(require_scope(CATALOG_READ_SCOPE)),
) -> ListingOut:
    listing = CatalogService(session).get_listing(listing_id)
    if listing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Listing not found.")
    return ListingOut.from_model(listing)
