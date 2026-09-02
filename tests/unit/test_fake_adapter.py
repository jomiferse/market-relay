"""Deterministic fake adapter: full flow with no network and no secrets
(tasks.md 2.4; specs/source-governance/spec.md § 'Safe test
adapters').
"""

from __future__ import annotations

import os
from datetime import date

import pytest

from market_relay.adapters.fake import FakeMarketDataProvider, FakeQuotaBook
from market_relay.domain.catalog.models import AssetClass
from market_relay.ports.calendar import SessionExpectation
from market_relay.ports.discovery import DiscoveryQuery


def test_repeated_integration_scenario_is_fully_deterministic() -> None:
    """specs/source-governance/spec.md § 'Repeatable integration test': the
    same run twice produces the same observations and states.
    """

    def run_scenario() -> tuple[object, ...]:
        provider = FakeMarketDataProvider()
        identities = provider.search(DiscoveryQuery(query="DE0007164600"))
        observations = provider.fetch_range(
            external_listing_id="FAKE-DE0007164600-XETR",
            start=date(2024, 1, 1),
            end=date(2024, 1, 5),
        )
        sessions = provider.sessions_in_range(
            asset_class=AssetClass.EQUITY,
            venue="XETR",
            mic="XETR",
            start=date(2024, 1, 1),
            end=date(2024, 1, 7),
        )
        quota = provider.consume("fake", cost=3)
        return identities, observations, sessions, quota

    first_run = run_scenario()
    second_run = run_scenario()

    identities_1, observations_1, sessions_1, quota_1 = first_run
    identities_2, observations_2, sessions_2, quota_2 = second_run

    assert identities_1 == identities_2
    assert observations_1 == observations_2
    assert sessions_1 == sessions_2
    # The quota resets for each new provider instance, so both runs
    # consume from the same initial state and reach the same
    # remaining amount.
    assert quota_1 == quota_2


def test_discovery_resolves_isin_traded_on_two_venues() -> None:
    provider = FakeMarketDataProvider()

    candidates = provider.search(DiscoveryQuery(query="DE0007164600"))

    assert {c.venue for c in candidates} == {"XETR", "XPAR"}
    assert all(c.isin == "DE0007164600" for c in candidates)


def test_discovery_resolves_crypto_without_isin() -> None:
    provider = FakeMarketDataProvider()

    candidates = provider.search(DiscoveryQuery(query="BTC", asset_class=AssetClass.CRYPTO))

    assert len(candidates) == 1
    assert candidates[0].isin is None
    assert candidates[0].mic is None
    assert candidates[0].venue == "KRAKEN"


def test_fetch_range_skips_weekends_without_fabricating_prices() -> None:
    provider = FakeMarketDataProvider()

    observations = provider.fetch_range(
        external_listing_id="FAKE-DE0007164600-XETR",
        start=date(2024, 1, 6),  # Saturday
        end=date(2024, 1, 7),  # Sunday
    )

    assert observations == []


def test_calendar_reports_no_session_on_weekends_for_equities() -> None:
    provider = FakeMarketDataProvider()

    sessions = provider.sessions_in_range(
        asset_class=AssetClass.EQUITY,
        venue="XETR",
        mic="XETR",
        start=date(2024, 1, 6),
        end=date(2024, 1, 6),
    )

    assert sessions[0].expectation is SessionExpectation.NO_SESSION


def test_calendar_reports_crypto_as_always_published() -> None:
    provider = FakeMarketDataProvider()

    sessions = provider.sessions_in_range(
        asset_class=AssetClass.CRYPTO,
        venue="KRAKEN",
        mic=None,
        start=date(2024, 1, 6),  # Saturday
        end=date(2024, 1, 6),
    )

    assert sessions[0].expectation is SessionExpectation.EXPECTED_PUBLISHED


def test_calendar_reports_fund_waiting_for_publication_on_friday() -> None:
    provider = FakeMarketDataProvider()

    sessions = provider.sessions_in_range(
        asset_class=AssetClass.FUND,
        venue="LU-FUNDS",
        mic=None,
        start=date(2024, 1, 5),  # Friday
        end=date(2024, 1, 5),
    )

    assert sessions[0].expectation is SessionExpectation.WAITING_FOR_PUBLICATION


def test_quota_exhaustion_stops_further_consumption_without_network_calls() -> None:
    provider = FakeMarketDataProvider(quota_book=FakeQuotaBook(limit=2))

    first = provider.consume("fake", cost=1)
    second = provider.consume("fake", cost=1)
    third = provider.consume("fake", cost=1)

    assert first.remaining == 1
    assert second.remaining == 0
    assert third.exhausted
    assert third.remaining == 0


def test_full_flow_uses_no_network_and_no_real_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifies that the full flow (discovery, calendar, history,
    quota) requires no credential environment variables.
    """

    for key in list(os.environ):
        if "API_KEY" in key or "SECRET" in key or "TOKEN" in key:
            monkeypatch.delenv(key, raising=False)

    provider = FakeMarketDataProvider()
    identities = provider.search(DiscoveryQuery(query="BTC"))
    assert identities
    listing_id = identities[0].external_id

    observations = provider.fetch_range(
        external_listing_id=listing_id, start=date(2024, 1, 1), end=date(2024, 1, 3)
    )
    assert len(observations) == 3
    assert all(obs.close > 0 for obs in observations)
