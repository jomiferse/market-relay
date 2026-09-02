"""Neutral port for market calendar and publication windows.

`specs/market-data-ingestion/spec.md` requires distinguishing exchange
sessions, deferred publication of funds, and 24/7 crypto markets,
representing what is not yet published as waiting rather than failure.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Protocol

from market_relay.domain.catalog.models import AssetClass


class SessionExpectation(StrEnum):
    """What to expect for a specific date for a listing."""

    # A session exists and the close should already have been published.
    EXPECTED_PUBLISHED = "EXPECTED_PUBLISHED"
    # A session exists but publication is still within its expected window
    # (e.g. fund NAV).
    WAITING_FOR_PUBLICATION = "WAITING_FOR_PUBLICATION"
    # There is no session for that date (market closed, weekend, holiday).
    NO_SESSION = "NO_SESSION"


@dataclass(frozen=True, slots=True)
class SessionCheck:
    session_date: date
    expectation: SessionExpectation


class MarketCalendarPort(Protocol):
    """Calendar contract, differentiated by asset class and venue."""

    def sessions_in_range(
        self,
        *,
        asset_class: AssetClass,
        venue: str,
        mic: str | None,
        start: date,
        end: date,
    ) -> list[SessionCheck]:
        """Classifies each date in the `[start, end]` range according to
        `SessionExpectation`, without consuming quota for `NO_SESSION`
        dates. Asset class determines the strategy: equities/ETFs by
        exchange calendar, funds by NAV window, crypto 24/7.
        """
        ...
