"""Real append-only for `observations`: `UPDATE`/`DELETE` always fail.

Before migration `0003` and the ORM guard, the append-only guarantee
described in `tasks.md` 4.1 depended solely on the discipline of
`ObservationStore` (it never emits `UPDATE`): any code with access to the
session could violate it. These tests demonstrate that a direct
`UPDATE`/`DELETE` fails both at the ORM level (`before_update`/`before_delete`
event) and at the database level (trigger from migration `0003`, effective
even against raw SQL outside the ORM), and that the row keeps existing and
remains intact after each attempt — never deleted nor replaced.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import bindparam, delete, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from market_relay.domain.catalog import AssetClass, CatalogService
from market_relay.domain.catalog.models import Listing
from market_relay.domain.observations import ObservationInput, ObservationStore
from market_relay.domain.observations.models import (
    Observation,
    ObservationImmutableError,
    ObservationType,
)

RETRIEVED_AT = datetime(2026, 1, 5, 22, 0, tzinfo=UTC)


def _make_listing(session: Session) -> Listing:
    catalog = CatalogService(session)
    instrument = catalog.register_instrument(
        asset_class=AssetClass.EQUITY, name="SAP SE", isin="DE0007164600"
    )
    return catalog.add_listing(
        instrument=instrument, venue="XETR", mic="XETR", ticker="SAP", currency="EUR"
    )


def _record_one(session: Session, listing_id) -> Observation:
    store = ObservationStore(session)
    outcome = store.record(
        ObservationInput(
            listing_id=listing_id,
            source="fake",
            credential_scope="default",
            external_listing_id="FAKE-DE0007164600-XETR",
            session_date=date(2026, 1, 5),
            observation_type=ObservationType.EOD_CLOSE,
            currency="EUR",
            close=Decimal("120.50"),
            retrieved_at=RETRIEVED_AT,
        )
    )
    session.commit()
    return outcome.observation


def test_orm_attribute_mutation_is_rejected_before_flush(db_session) -> None:
    """Mutating an attribute and calling `flush()` triggers the ORM guard
    before any `UPDATE` SQL is emitted."""

    listing = _make_listing(db_session)
    observation = _record_one(db_session, listing.id)

    observation.close = Decimal("999.99")
    with pytest.raises(ObservationImmutableError):
        db_session.flush()

    db_session.rollback()
    unchanged = db_session.get(Observation, observation.id)
    assert unchanged is not None
    assert unchanged.close == Decimal("120.50")


def test_orm_session_delete_is_rejected(db_session) -> None:
    listing = _make_listing(db_session)
    observation = _record_one(db_session, listing.id)

    db_session.delete(observation)
    with pytest.raises(ObservationImmutableError):
        db_session.flush()

    db_session.rollback()
    unchanged = db_session.get(Observation, observation.id)
    assert unchanged is not None


def test_raw_core_update_is_rejected_by_database_trigger(db_session) -> None:
    """An `UPDATE` built with SQLAlchemy Core (without going through the
    ORM's unit-of-work, and therefore without triggering the
    `before_update` events) is still blocked by the database trigger."""

    listing = _make_listing(db_session)
    observation = _record_one(db_session, listing.id)

    with pytest.raises(DBAPIError):
        db_session.execute(
            update(Observation)
            .where(Observation.id == observation.id)
            .values(close=Decimal("1.00"))
        )
        db_session.flush()

    db_session.rollback()
    unchanged = db_session.get(Observation, observation.id)
    assert unchanged is not None
    assert unchanged.close == Decimal("120.50")


def test_raw_core_delete_is_rejected_by_database_trigger(db_session) -> None:
    listing = _make_listing(db_session)
    observation = _record_one(db_session, listing.id)

    with pytest.raises(DBAPIError):
        db_session.execute(delete(Observation).where(Observation.id == observation.id))
        db_session.flush()

    db_session.rollback()
    unchanged = db_session.get(Observation, observation.id)
    assert unchanged is not None


def test_raw_sql_update_is_rejected_by_database_trigger(db_session) -> None:
    """The trigger protects even against textual SQL entirely outside the
    ORM, the hardest defense to bypass. The `id` parameter is bound with
    the column's real type (`bindparam(..., type_=Observation.id.type)`)
    because SQLite stores `Uuid` as hex without dashes: comparing against
    `str(uuid)` (with dashes) would not trigger the guard, it would simply
    find no row to update.
    """

    listing = _make_listing(db_session)
    observation = _record_one(db_session, listing.id)

    with pytest.raises(DBAPIError):
        db_session.execute(
            text("UPDATE observations SET close = :close WHERE id = :id").bindparams(
                bindparam("id", type_=Observation.id.type)
            ),
            {"close": "1.00", "id": observation.id},
        )
        db_session.flush()

    db_session.rollback()
    unchanged = db_session.get(Observation, observation.id)
    assert unchanged is not None
    assert unchanged.close == Decimal("120.50")


def test_raw_sql_delete_is_rejected_by_database_trigger(db_session) -> None:
    listing = _make_listing(db_session)
    observation = _record_one(db_session, listing.id)

    with pytest.raises(DBAPIError):
        db_session.execute(
            text("DELETE FROM observations WHERE id = :id").bindparams(
                bindparam("id", type_=Observation.id.type)
            ),
            {"id": observation.id},
        )
        db_session.flush()

    db_session.rollback()
    unchanged = db_session.get(Observation, observation.id)
    assert unchanged is not None


def test_new_revision_insert_is_never_blocked(db_session) -> None:
    """The trigger only blocks `UPDATE`/`DELETE`: a legitimate correction
    represented as a new row with incremented `revision` keeps working
    frictionlessly (tasks.md 4.1)."""

    listing = _make_listing(db_session)
    store = ObservationStore(db_session)
    first = store.record(
        ObservationInput(
            listing_id=listing.id,
            source="fake",
            credential_scope="default",
            external_listing_id="FAKE-DE0007164600-XETR",
            session_date=date(2026, 1, 5),
            observation_type=ObservationType.EOD_CLOSE,
            currency="EUR",
            close=Decimal("120.50"),
            retrieved_at=RETRIEVED_AT,
        )
    )
    corrected = store.record(
        ObservationInput(
            listing_id=listing.id,
            source="fake",
            credential_scope="default",
            external_listing_id="FAKE-DE0007164600-XETR",
            session_date=date(2026, 1, 5),
            observation_type=ObservationType.EOD_CLOSE,
            currency="EUR",
            close=Decimal("121.00"),
            retrieved_at=RETRIEVED_AT,
        )
    )
    db_session.commit()

    assert corrected.observation.revision == first.observation.revision + 1
    rows = db_session.query(Observation).all()
    assert len(rows) == 2
    assert {row.close for row in rows} == {Decimal("120.50"), Decimal("121.00")}
