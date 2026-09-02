"""Catalog: one-to-many, crypto without ISIN, and ambiguity (tasks.md 2.1)."""

from __future__ import annotations

import pytest

from market_relay.domain.catalog import (
    AmbiguousMatchError,
    AssetClass,
    CatalogService,
    ListingSearchCriteria,
)


def test_isin_with_several_listings_returns_differentiated_quotes(db_session) -> None:
    """specs/instrument-catalog/spec.md § 'ISIN with several listings'."""

    catalog = CatalogService(db_session)
    instrument = catalog.register_instrument(
        asset_class=AssetClass.EQUITY, name="SAP SE", isin="DE0007164600"
    )
    xetra = catalog.add_listing(
        instrument=instrument, venue="XETR", mic="XETR", ticker="SAP", currency="EUR"
    )
    paris = catalog.add_listing(
        instrument=instrument, venue="XPAR", mic="XPAR", ticker="SAP", currency="EUR"
    )

    listings = catalog.find_listings(ListingSearchCriteria(isin="DE0007164600"))

    assert {listing.id for listing in listings} == {xetra.id, paris.id}
    assert {listing.mic for listing in listings} == {"XETR", "XPAR"}


def test_crypto_without_isin_or_mic_is_represented(db_session) -> None:
    """specs/instrument-catalog/spec.md § 'Crypto asset without ISIN or MIC'."""

    catalog = CatalogService(db_session)
    instrument = catalog.register_instrument(asset_class=AssetClass.CRYPTO, name="Bitcoin")
    listing = catalog.add_listing(
        instrument=instrument, venue="KRAKEN", ticker="BTC", currency="EUR"
    )

    assert instrument.isin is None
    assert instrument.figi is None
    assert listing.mic is None
    assert listing.venue == "KRAKEN"


def test_ambiguous_eur_match_is_rejected_without_silent_linking(db_session) -> None:
    """specs/instrument-catalog/spec.md § 'Ambiguous EUR match'."""

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

    with pytest.raises(AmbiguousMatchError) as exc_info:
        catalog.resolve_single_listing(ListingSearchCriteria(isin="DE0007164600", currency="EUR"))

    assert len(exc_info.value.candidates) == 2


def test_resolve_single_listing_succeeds_with_disambiguating_mic(db_session) -> None:
    catalog = CatalogService(db_session)
    instrument = catalog.register_instrument(
        asset_class=AssetClass.EQUITY, name="SAP SE", isin="DE0007164600"
    )
    xetra = catalog.add_listing(
        instrument=instrument, venue="XETR", mic="XETR", ticker="SAP", currency="EUR"
    )
    catalog.add_listing(
        instrument=instrument, venue="XPAR", mic="XPAR", ticker="SAP", currency="EUR"
    )

    resolved = catalog.resolve_single_listing(
        ListingSearchCriteria(isin="DE0007164600", mic="XETR")
    )

    assert resolved.id == xetra.id


def test_external_identity_carries_provenance_and_validity(db_session) -> None:
    catalog = CatalogService(db_session)
    instrument = catalog.register_instrument(asset_class=AssetClass.CRYPTO, name="Bitcoin")
    listing = catalog.add_listing(
        instrument=instrument, venue="KRAKEN", ticker="BTC", currency="EUR"
    )

    from datetime import date

    identity = catalog.link_external_identity(
        listing=listing,
        source="fake",
        external_id="FAKE-BTC-KRAKEN",
        valid_from=date(2024, 1, 1),
    )

    assert identity.source == "fake"
    assert identity.valid_to is None
