"""Pydantic schemas for the versioned HTTP contract v1 (tasks.md 5.1).

`specs/consumer-api/spec.md` requires observation responses to include
effective date, currency, provenance and publication state, and that the
API never claim to offer real-time prices (`is_eod` is always `True`: the
MVP has no other observation nature). These models are the API's only
public surface: they never include quota, credentials, policy evidence, or
the detailed reason for unavailability (specs/source-governance/spec.md §
"Credential protection"; specs/consumer-api/spec.md § "Stored
non-redistributable data").
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

from market_relay.domain.catalog.models import AssetClass
from market_relay.domain.observations.models import ObservationType

if TYPE_CHECKING:
    from market_relay.domain.catalog.models import Instrument, Listing


class ErrorResponse(BaseModel):
    """Shape of every API error: a non-sensitive detail, never internal
    data, configuration, or the existence of secrets.
    """

    detail: str


class InstrumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    instrument_id: uuid.UUID
    asset_class: AssetClass
    name: str
    isin: str | None = None
    figi: str | None = None

    @classmethod
    def from_model(cls, instrument: Instrument) -> InstrumentOut:
        return cls(
            instrument_id=instrument.id,
            asset_class=instrument.asset_class,
            name=instrument.name,
            isin=instrument.isin,
            figi=instrument.figi,
        )


class ListingOut(BaseModel):
    """A listing, with its instrument embedded (specs/instrument-catalog
    § "Canonical identity and listings": an ISIN is never assumed to
    identify a single listing).
    """

    model_config = ConfigDict(from_attributes=True)

    listing_id: uuid.UUID
    instrument: InstrumentOut
    venue: str
    mic: str | None = None
    ticker: str
    currency: str

    @classmethod
    def from_model(cls, listing: Listing) -> ListingOut:
        return cls(
            listing_id=listing.id,
            instrument=InstrumentOut.from_model(listing.instrument),
            venue=listing.venue,
            mic=listing.mic,
            ticker=listing.ticker,
            currency=listing.currency,
        )


class InstrumentSearchResponse(BaseModel):
    """`results` can have more than one element for the same instrument
    (specs/instrument-catalog § "ISIN with several listings"): the search
    never picks an arbitrary listing on the consumer's behalf.
    """

    results: list[ListingOut]


class ObservationAvailability(StrEnum):
    """Explicit state of an observation queried by date.

    `NO_SESSION` and `WAITING_FOR_PUBLICATION` distinguish the *expected*
    absence (weekend, holiday, NAV still within its window) from pending or
    blocked data (`UNAVAILABLE`), which deliberately groups "not yet
    ingested" and "policy does not authorize publication": the API never
    reveals which of the two applies (specs/consumer-api/spec.md § "Stored
    non-redistributable data": "a non-sensitive unavailability state").
    """

    OK = "OK"
    NO_SESSION = "NO_SESSION"
    WAITING_FOR_PUBLICATION = "WAITING_FOR_PUBLICATION"
    UNAVAILABLE = "UNAVAILABLE"


class ObservationValueOut(BaseModel):
    """Present only when `ObservationOut.availability == OK`."""

    observation_type: ObservationType
    # Always `True` in the MVP: the API only publishes EOD closes, never
    # real time (specs/consumer-api/spec.md § "Separation of
    # concerns").
    is_eod: bool = True
    currency: str
    close: Decimal
    source: str
    revision: int
    retrieved_at: datetime
    requires_attribution: bool
    attribution: str | None = None
    # `True` if another approved, publishable source disagrees for the same
    # listing and date (specs/market-observations/spec.md § "Two approved
    # sources disagree"): the discrepancy is exposed, never hidden by
    # averaging or merging values.
    has_discrepancy: bool


class ObservationOut(BaseModel):
    listing_id: uuid.UUID
    session_date: date
    availability: ObservationAvailability
    value: ObservationValueOut | None = None


class ObservationRangeResponse(BaseModel):
    listing_id: uuid.UUID
    observation_type: ObservationType
    start: date
    end: date
    observations: list[ObservationOut]


class DataStatusOut(BaseModel):
    """Data status of a listing, without exposing provenance or quota."""

    listing_id: uuid.UUID
    observation_type: ObservationType
    last_effective_date: date | None
    has_publishable_data: bool


class OperationalStatusOut(BaseModel):
    """Sanitized subset of `specs/operations/spec.md` §
    "Minimum observability", exposed to authorized consumers: never
    includes credentials, per-source quota detail, or internal job names.
    """

    environment: str
    pending_jobs: int
    oldest_pending_seconds: int | None
    stalled: bool


class SourceQuotaOut(BaseModel):
    """Quota state of a registered source. `source` is an internal adapter
    identifier (e.g. "fake"), never a credential; `error` (when present) is
    one of the bounded, generic codes from `domain.ingestion.error_codes`,
    never the provider's own exception text, sanitized or not.
    """

    source: str
    remaining: int | None
    limit: int | None
    exhausted: bool
    error: str | None = None


class SchedulerMetricsOut(BaseModel):
    """Sanitized operational metrics from tasks.md 6.2
    (specs/operations/spec.md § "Minimum observability"), reserved for a
    consumer holding the `operations:metrics` scope (never granted to
    Holdria by default): unlike `OperationalStatusOut`, it includes the
    internal source name per job so an operator can identify which one is
    stalled or out of quota, but never a credential or a provider's raw
    error text.
    """

    pending_jobs: int
    pending_jobs_by_source: dict[str, int]
    oldest_pending_seconds: float | None
    done_jobs: int
    failed_jobs_by_source: dict[str, int]
    quota_by_source: list[SourceQuotaOut]
    stalled_sources: list[str]
    # Durable counts of whole successful executions of each bounded phase
    # of the single scheduled entry point (tasks.md 6.1;
    # specs/operations/spec.md § "Minimum observability": "successful
    # scheduler and worker executions"), backed by `scheduler_runs`
    # rather than derived from individual job outcomes.
    scheduler_success_count: int
    worker_success_count: int
