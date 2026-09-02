"""Catalog service: registration and search of instruments and listings.

Implements `specs/instrument-catalog/spec.md`: instrument and listings are
represented separately, search does not assume that an ISIN identifies a
single listing, it supports crypto assets without ISIN or MIC, and it
rejects ambiguity surgically instead of resolving it silently.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from market_relay.domain.catalog.models import AssetClass, ExternalIdentity, Instrument, Listing


class AmbiguousMatchError(Exception):
    """Raised when the criteria are not enough to select a single listing."""

    def __init__(self, candidates: list[Listing]) -> None:
        self.candidates = candidates
        super().__init__(
            f"The search is ambiguous: {len(candidates)} listings match the given criteria."
        )


@dataclass(frozen=True, slots=True)
class ListingSearchCriteria:
    """Optional criteria to narrow the listing search."""

    isin: str | None = None
    figi: str | None = None
    ticker: str | None = None
    mic: str | None = None
    venue: str | None = None
    currency: str | None = None
    asset_class: AssetClass | None = None


class CatalogService:
    """Catalog use cases over a SQLAlchemy session."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def register_instrument(
        self,
        *,
        asset_class: AssetClass,
        name: str,
        isin: str | None = None,
        figi: str | None = None,
    ) -> Instrument:
        """Registers an instrument. `isin`/`figi` are left absent when they
        do not apply (e.g. crypto), without fabricating values.
        """

        instrument = Instrument(asset_class=asset_class, name=name, isin=isin, figi=figi)
        self._session.add(instrument)
        self._session.flush()
        return instrument

    def add_listing(
        self,
        *,
        instrument: Instrument,
        venue: str,
        ticker: str,
        currency: str,
        mic: str | None = None,
    ) -> Listing:
        """Adds a listing to an instrument. `mic` is optional: crypto assets
        use `venue` (e.g. the exchange) without MIC.
        """

        listing = Listing(
            instrument_id=instrument.id,
            venue=venue,
            ticker=ticker,
            currency=currency.upper(),
            mic=mic,
        )
        self._session.add(listing)
        self._session.flush()
        return listing

    def link_external_identity(
        self,
        *,
        listing: Listing,
        source: str,
        external_id: str,
        valid_from: date,
        valid_to: date | None = None,
    ) -> ExternalIdentity:
        """Links a provider identifier with provenance and a validity period."""

        identity = ExternalIdentity(
            listing_id=listing.id,
            source=source,
            external_id=external_id,
            valid_from=valid_from,
            valid_to=valid_to,
        )
        self._session.add(identity)
        self._session.flush()
        return identity

    def find_listings(self, criteria: ListingSearchCriteria) -> list[Listing]:
        """Returns all listings that satisfy the given criteria.

        Does not resolve ambiguity: when several listings satisfy the
        criteria, all of them are returned so the calling person or process
        can decide. See `resolve_single_listing` for the case that requires
        a single match.
        """

        stmt = select(Listing).join(Instrument)
        if criteria.isin is not None:
            stmt = stmt.where(Instrument.isin == criteria.isin)
        if criteria.figi is not None:
            stmt = stmt.where(Instrument.figi == criteria.figi)
        if criteria.asset_class is not None:
            stmt = stmt.where(Instrument.asset_class == criteria.asset_class)
        if criteria.ticker is not None:
            stmt = stmt.where(Listing.ticker == criteria.ticker)
        if criteria.mic is not None:
            stmt = stmt.where(Listing.mic == criteria.mic)
        if criteria.venue is not None:
            stmt = stmt.where(Listing.venue == criteria.venue)
        if criteria.currency is not None:
            stmt = stmt.where(Listing.currency == criteria.currency.upper())

        return list(self._session.scalars(stmt).all())

    def resolve_single_listing(self, criteria: ListingSearchCriteria) -> Listing:
        """Resolves a single listing deterministically.

        Raises `AmbiguousMatchError` when the criteria are not enough to
        select a listing (specs/instrument-catalog/spec.md § "Explicit and
        traceable resolution"). Never silently links an arbitrary candidate.
        """

        candidates = self.find_listings(criteria)
        if len(candidates) != 1:
            raise AmbiguousMatchError(candidates)
        return candidates[0]

    def get_instrument(self, instrument_id: uuid.UUID) -> Instrument | None:
        return self._session.get(Instrument, instrument_id)

    def get_listing(self, listing_id: uuid.UUID) -> Listing | None:
        return self._session.get(Listing, listing_id)
