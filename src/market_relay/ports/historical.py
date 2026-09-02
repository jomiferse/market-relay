"""Neutral port for retrieving historical EOD prices."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol

from market_relay.domain.observations.models import ObservationType


@dataclass(frozen=True, slots=True)
class RawObservation:
    """Raw value returned by a source, uninterpreted and unadjusted.

    `close` SHALL be the raw value published by the source
    (specs/market-observations/spec.md § "Raw value without implicit
    adjustments"); `adjusted_close` is kept separately and never
    substitutes `close`.
    """

    external_listing_id: str
    session_date: date
    observation_type: ObservationType
    currency: str
    close: Decimal
    open: Decimal | None = None
    high: Decimal | None = None
    low: Decimal | None = None
    adjusted_close: Decimal | None = None


class HistoricalPricePort(Protocol):
    """Contract for retrieving historical data by date range."""

    def fetch_range(
        self, *, external_listing_id: str, start: date, end: date
    ) -> list[RawObservation]:
        """Returns the observations available in `[start, end]`.

        An adapter SHALL omit dates with no expected session rather than
        fabricate a value (specs/market-data-ingestion/spec.md).
        """
        ...
