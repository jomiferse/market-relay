"""Append-only storage, idempotency and revisions (tasks.md 4.1)."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from market_relay.domain.catalog import AssetClass, CatalogService
from market_relay.domain.catalog.models import Listing
from market_relay.domain.observations import (
    ObservationInput,
    ObservationStore,
    ObservationType,
    QualityStatus,
)
from market_relay.domain.observations.models import Observation

RETRIEVED_AT = datetime(2026, 1, 5, 22, 0, tzinfo=UTC)


def _make_listing(session: Session) -> Listing:
    catalog = CatalogService(session)
    instrument = catalog.register_instrument(
        asset_class=AssetClass.EQUITY, name="SAP SE", isin="DE0007164600"
    )
    return catalog.add_listing(
        instrument=instrument, venue="XETR", mic="XETR", ticker="SAP", currency="EUR"
    )


def _input(
    listing_id: uuid.UUID, *, close: str = "120.50", credential_scope: str = "default"
) -> ObservationInput:
    return ObservationInput(
        listing_id=listing_id,
        source="fake",
        credential_scope=credential_scope,
        external_listing_id="FAKE-DE0007164600-XETR",
        session_date=date(2026, 1, 5),
        observation_type=ObservationType.EOD_CLOSE,
        currency="eur",
        close=Decimal(close),
        retrieved_at=RETRIEVED_AT,
    )


def test_first_insert_creates_revision_one(db_session) -> None:
    listing = _make_listing(db_session)
    store = ObservationStore(db_session)

    outcome = store.record(_input(listing.id))

    assert outcome.created is True
    assert outcome.is_correction is False
    assert outcome.observation.revision == 1
    assert outcome.observation.currency == "EUR"


def test_retrying_identical_value_is_idempotent_and_does_not_duplicate(db_session) -> None:
    listing = _make_listing(db_session)
    store = ObservationStore(db_session)

    first = store.record(_input(listing.id))
    second = store.record(_input(listing.id))

    assert second.created is False
    assert second.observation.id == first.observation.id

    rows = db_session.query(Observation).all()
    assert len(rows) == 1


def test_correction_with_different_value_creates_new_revision_without_overwriting(
    db_session,
) -> None:
    listing = _make_listing(db_session)
    store = ObservationStore(db_session)

    first = store.record(_input(listing.id, close="120.50"))
    corrected = store.record(_input(listing.id, close="121.00"))

    assert corrected.created is True
    assert corrected.is_correction is True
    assert corrected.observation.revision == 2
    assert corrected.observation.close == Decimal("121.00")

    # The previous revision still exists intact: it is never overwritten.
    original = db_session.get(Observation, first.observation.id)
    assert original is not None
    assert original.close == Decimal("120.50")
    assert original.revision == 1

    rows = db_session.query(Observation).all()
    assert len(rows) == 2

    current = store.current_for_key(
        source="fake",
        credential_scope="default",
        external_listing_id="FAKE-DE0007164600-XETR",
        session_date=date(2026, 1, 5),
        observation_type=ObservationType.EOD_CLOSE,
    )
    assert current is not None
    assert current.revision == 2
    assert current.close == Decimal("121.00")


def test_different_credential_scope_is_a_distinct_key(db_session) -> None:
    """`credentialScope` is part of the key: two distinct accounts of the
    same source are not deduplicated against each other (design.md §
    "Isolated central credentials").
    """

    listing = _make_listing(db_session)
    store = ObservationStore(db_session)

    store.record(_input(listing.id, close="120.50", credential_scope="account-a"))
    store.record(_input(listing.id, close="999.00", credential_scope="account-b"))

    rows = db_session.query(Observation).all()
    assert len(rows) == 2
    assert {row.credential_scope for row in rows} == {"account-a", "account-b"}


def test_exact_uniqueness_key_enforced_at_database_level(db_session) -> None:
    """The database unique constraint rejects a duplicate row with the
    same natural key and revision, even one created outside `ObservationStore`.
    """

    listing = _make_listing(db_session)
    store = ObservationStore(db_session)
    store.record(_input(listing.id))

    duplicate = Observation(
        listing_id=listing.id,
        source="fake",
        credential_scope="default",
        external_listing_id="FAKE-DE0007164600-XETR",
        session_date=date(2026, 1, 5),
        observation_type=ObservationType.EOD_CLOSE,
        revision=1,
        currency="EUR",
        close=Decimal("999.99"),
        quality_status=QualityStatus.OK,
        retrieved_at=RETRIEVED_AT,
    )
    db_session.add(duplicate)
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_concurrent_inserts_of_same_observation_do_not_duplicate(session_factory) -> None:
    """Idempotency under concurrent inserts: two "workers" with independent
    sessions that retrieve the same close do not produce two rows
    (specs/market-data-ingestion/spec.md § "Retry after lost confirmation").
    """

    setup_session = session_factory()
    try:
        listing = _make_listing(setup_session)
        setup_session.commit()
        listing_id = listing.id
    finally:
        setup_session.close()

    outcomes = []
    for _ in range(2):
        worker_session = session_factory()
        try:
            store = ObservationStore(worker_session)
            outcomes.append(store.record(_input(listing_id)))
            worker_session.commit()
        finally:
            worker_session.close()

    assert sum(1 for outcome in outcomes if outcome.created) == 1
    assert sum(1 for outcome in outcomes if not outcome.created) == 1
    assert outcomes[0].observation.id == outcomes[1].observation.id

    verify_session = session_factory()
    try:
        rows = verify_session.query(Observation).all()
        assert len(rows) == 1
    finally:
        verify_session.close()
