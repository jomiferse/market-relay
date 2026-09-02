"""Observations v1 endpoints applying the publication policy gate.

tasks.md 5.1 and 5.3; `specs/market-observations/spec.md`;
`specs/consumer-api/spec.md`. No stored observation whose source lacks
current `STORE`+`DISPLAY`+`REDISTRIBUTE` ever reaches the response
(see `market_relay.api.services.observation_view`).
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from market_relay.adapters.registry import get_calendar_for_listing
from market_relay.api.deps import get_db, get_settings_dep, require_scope
from market_relay.api.schemas import ErrorResponse, ObservationOut, ObservationRangeResponse
from market_relay.api.services.observation_view import (
    build_observation_range,
    find_latest_observation,
)
from market_relay.config import Settings
from market_relay.domain.catalog.models import Listing
from market_relay.domain.catalog.service import CatalogService
from market_relay.domain.governance.consumer_auth import ConsumerIdentity
from market_relay.domain.observations.models import ObservationType

OBSERVATIONS_READ_SCOPE = "observations:read"

# Maximum range per request: bounds the work per response the same way
# `RecoveryLimits` bounds ingestion (design.md § "Range-based recovery");
# a consumer needing more history SHALL paginate by dates instead of
# receiving an unbounded sweep.
_MAX_RANGE_DAYS = 366

router = APIRouter(tags=["observations"])

_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "Missing or invalid credential."},
    403: {"model": ErrorResponse, "description": "Consumer without the required scope."},
    404: {"model": ErrorResponse, "description": "Listing does not exist."},
}


def _resolve_listing(session: Session, listing_id: uuid.UUID) -> Listing:
    listing = CatalogService(session).get_listing(listing_id)
    if listing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Listing not found.")
    return listing


@router.get(
    "/listings/{listing_id}/observations/latest",
    response_model=ObservationOut,
    responses=_RESPONSES,
    summary="Latest publishable EOD observation",
)
def latest_observation(
    listing_id: uuid.UUID,
    observation_type: ObservationType = Query(default=ObservationType.EOD_CLOSE),
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
    _identity: ConsumerIdentity = Depends(require_scope(OBSERVATIONS_READ_SCOPE)),
) -> ObservationOut:
    """The most recent publishable EOD observation for the listing.

    Never a real-time price: `session_date` identifies the effective date
    of the close returned (specs/consumer-api/spec.md § "EOD price
    request").
    """

    listing = _resolve_listing(session, listing_id)
    calendar = get_calendar_for_listing(mic=listing.mic, venue=listing.venue)
    return find_latest_observation(
        session=session,
        listing=listing,
        observation_type=observation_type,
        settings=settings,
        calendar=calendar,
    )


_RANGE_RESPONSES: dict[int | str, dict[str, Any]] = {
    **_RESPONSES,
    422: {"model": ErrorResponse, "description": "Invalid date range."},
}


@router.get(
    "/listings/{listing_id}/observations",
    response_model=ObservationRangeResponse,
    responses=_RANGE_RESPONSES,
    summary="Range of publishable EOD observations",
)
def observation_range(
    listing_id: uuid.UUID,
    start: date = Query(..., description="First date of the range, inclusive."),
    end: date = Query(..., description="Last date of the range, inclusive."),
    observation_type: ObservationType = Query(default=ObservationType.EOD_CLOSE),
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
    _identity: ConsumerIdentity = Depends(require_scope(OBSERVATIONS_READ_SCOPE)),
) -> ObservationRangeResponse:
    """One observation per date in the range, including days without a session.

    specs/consumer-api/spec.md § "Range with non-trading days": the range
    returns only effective observations and lets callers distinguish an
    expected absence from pending or failed data via `availability`.
    """

    if end < start:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="`end` cannot be earlier than `start`.",
        )
    if (end - start).days > _MAX_RANGE_DAYS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"The maximum range per request is {_MAX_RANGE_DAYS} days.",
        )

    listing = _resolve_listing(session, listing_id)
    calendar = get_calendar_for_listing(mic=listing.mic, venue=listing.venue)
    observations = build_observation_range(
        session=session,
        listing=listing,
        observation_type=observation_type,
        start=start,
        end=end,
        settings=settings,
        calendar=calendar,
    )
    return ObservationRangeResponse(
        listing_id=listing_id,
        observation_type=observation_type,
        start=start,
        end=end,
        observations=observations,
    )
