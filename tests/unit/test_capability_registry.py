"""Provider capabilities compose independently and calendars route by listing."""

from __future__ import annotations

from datetime import date

import pytest

from market_relay.adapters import registry
from market_relay.domain.catalog.models import AssetClass
from market_relay.ports.calendar import SessionCheck, SessionExpectation
from market_relay.ports.discovery import DiscoveredIdentity, DiscoveryQuery
from market_relay.ports.historical import RawObservation


class IdentityOnly:
    def search(self, query: DiscoveryQuery) -> list[DiscoveredIdentity]:
        return []


class PricesOnly:
    def fetch_range(
        self, *, external_listing_id: str, start: date, end: date
    ) -> list[RawObservation]:
        return []


class VenueCalendar:
    def __init__(self, expectation: SessionExpectation) -> None:
        self.expectation = expectation

    def sessions_in_range(
        self,
        *,
        asset_class: AssetClass,
        venue: str,
        mic: str | None,
        start: date,
        end: date,
    ) -> list[SessionCheck]:
        return [SessionCheck(start, self.expectation)]


def test_identifier_and_price_sources_register_independently(monkeypatch) -> None:
    identity = IdentityOnly()
    prices = PricesOnly()
    monkeypatch.setitem(registry._DISCOVERY_ADAPTERS, "identity-only", identity)
    monkeypatch.setitem(registry._HISTORICAL_ADAPTERS, "prices-only", prices)

    assert registry.get_discovery_port("identity-only") is identity
    assert registry.get_historical_price_port("prices-only") is prices
    with pytest.raises(registry.UnknownSourceError):
        registry.get_historical_price_port("identity-only")
    with pytest.raises(registry.UnknownSourceError):
        registry.get_discovery_port("prices-only")


def test_calendar_routing_uses_mic_and_not_price_precedence(monkeypatch) -> None:
    xetra = VenueCalendar(SessionExpectation.NO_SESSION)
    paris = VenueCalendar(SessionExpectation.EXPECTED_PUBLISHED)
    monkeypatch.setitem(registry._CALENDAR_ADAPTERS, "xetra-calendar", xetra)
    monkeypatch.setitem(registry._CALENDAR_ADAPTERS, "paris-calendar", paris)
    monkeypatch.setattr(
        registry,
        "_CALENDAR_ROUTES",
        {"XETR": "xetra-calendar", "XPAR": "paris-calendar"},
    )

    assert registry.get_calendar_for_listing(mic="XETR", venue="Xetra") is xetra
    assert registry.get_calendar_for_listing(mic="XPAR", venue="Paris") is paris
    # Price order is intentionally absent from the calendar API.
    assert registry.get_calendar_for_listing(mic="XETR", venue="Xetra") is xetra


def test_missing_calendar_is_deterministic(monkeypatch) -> None:
    monkeypatch.setattr(registry, "_CALENDAR_ROUTES", {})
    with pytest.raises(registry.CalendarUnavailableError, match="No calendar is configured"):
        registry.get_calendar_for_listing(mic="XLON", venue="London")
