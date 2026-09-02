"""Deterministic selection with no silent merging (tasks.md 4.2)."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from market_relay.domain.catalog import AssetClass, CatalogService
from market_relay.domain.catalog.models import Listing
from market_relay.domain.governance import PolicyCapability, PolicyGate, PolicyStatus
from market_relay.domain.observations import (
    NoEligibleObservationError,
    ObservationInput,
    ObservationSelector,
    ObservationStore,
    ObservationType,
    SourcePriorityPolicy,
)
from market_relay.domain.observations.models import Observation

SESSION_DATE = date(2026, 1, 5)
RETRIEVED_AT = datetime(2026, 1, 5, 22, 0, tzinfo=UTC)


def _make_listing(session: Session) -> Listing:
    catalog = CatalogService(session)
    instrument = catalog.register_instrument(
        asset_class=AssetClass.EQUITY, name="SAP SE", isin="DE0007164600"
    )
    return catalog.add_listing(
        instrument=instrument, venue="XETR", mic="XETR", ticker="SAP", currency="EUR"
    )


def _authorize_publication(session: Session, source: str) -> None:
    """Approves `STORE`, `DISPLAY` and `REDISTRIBUTE` for `source`:
    precondition of `ObservationSelector`, which now derives publishability
    dynamically from `PolicyGate` instead of a flag stored on the row.
    """

    gate = PolicyGate(session)
    for capability in (
        PolicyCapability.STORE,
        PolicyCapability.DISPLAY,
        PolicyCapability.REDISTRIBUTE,
    ):
        gate.record_decision(
            source=source,
            capability=capability,
            status=PolicyStatus.APPROVED,
            evidence_reference=f"https://{source}.example/terms#{capability.value.lower()}",
            reviewed_by="ops@holdria.test",
        )


def _record(
    store: ObservationStore,
    listing_id: uuid.UUID,
    *,
    source: str,
    close: str,
    adjusted_close: str | None = None,
    retrieved_at: datetime = RETRIEVED_AT,
) -> Observation:
    return store.record(
        ObservationInput(
            listing_id=listing_id,
            source=source,
            credential_scope="default",
            external_listing_id=f"FAKE-{source}",
            session_date=SESSION_DATE,
            observation_type=ObservationType.EOD_CLOSE,
            currency="EUR",
            close=Decimal(close),
            adjusted_close=Decimal(adjusted_close) if adjusted_close else None,
            retrieved_at=retrieved_at,
        )
    ).observation


def test_selection_prefers_first_source_in_policy_order(db_session) -> None:
    listing = _make_listing(db_session)
    store = ObservationStore(db_session)
    _record(store, listing.id, source="primary", close="100.00")
    _record(store, listing.id, source="secondary", close="101.00")
    _authorize_publication(db_session, "primary")
    _authorize_publication(db_session, "secondary")

    selector = ObservationSelector(db_session)
    policy = SourcePriorityPolicy(name="primary-first", ordered_sources=("primary", "secondary"))

    result = selector.select(
        listing_id=listing.id,
        session_date=SESSION_DATE,
        observation_type=ObservationType.EOD_CLOSE,
        policy=policy,
    )

    assert result.selected.source == "primary"
    assert result.selected.close == Decimal("100.00")
    assert result.policy_name == "primary-first"


def test_discrepancy_between_sources_is_visible_not_merged(db_session) -> None:
    """specs/market-observations/spec.md § 'Two approved sources differ':
    the response identifies the selected value, its source, and exposes
    the alternative — it never averages or merges the two closes.
    """

    listing = _make_listing(db_session)
    store = ObservationStore(db_session)
    _record(store, listing.id, source="primary", close="100.00")
    _record(store, listing.id, source="secondary", close="105.00")
    _authorize_publication(db_session, "primary")
    _authorize_publication(db_session, "secondary")

    selector = ObservationSelector(db_session)
    policy = SourcePriorityPolicy(name="primary-first", ordered_sources=("primary", "secondary"))
    result = selector.select(
        listing_id=listing.id,
        session_date=SESSION_DATE,
        observation_type=ObservationType.EOD_CLOSE,
        policy=policy,
    )

    assert result.has_discrepancy is True
    assert result.selected.close == Decimal("100.00")
    assert {alt.source for alt in result.alternatives} == {"secondary"}
    assert result.alternatives[0].close == Decimal("105.00")
    # The value is not an average or a merge of both.
    assert result.selected.close not in (Decimal("102.50"),)


def test_close_is_selected_never_adjusted_close(db_session) -> None:
    listing = _make_listing(db_session)
    store = ObservationStore(db_session)
    _record(store, listing.id, source="primary", close="100.00", adjusted_close="95.00")
    _authorize_publication(db_session, "primary")

    selector = ObservationSelector(db_session)
    policy = SourcePriorityPolicy(name="primary-first", ordered_sources=("primary",))
    result = selector.select(
        listing_id=listing.id,
        session_date=SESSION_DATE,
        observation_type=ObservationType.EOD_CLOSE,
        policy=policy,
    )

    assert result.selected.close == Decimal("100.00")
    assert result.selected.adjusted_close == Decimal("95.00")
    assert result.selected.close != result.selected.adjusted_close


def test_source_absent_from_policy_is_never_considered(db_session) -> None:
    listing = _make_listing(db_session)
    store = ObservationStore(db_session)
    _record(store, listing.id, source="unlisted-source", close="100.00")

    selector = ObservationSelector(db_session)
    policy = SourcePriorityPolicy(name="only-primary", ordered_sources=("primary",))

    with pytest.raises(NoEligibleObservationError):
        selector.select(
            listing_id=listing.id,
            session_date=SESSION_DATE,
            observation_type=ObservationType.EOD_CLOSE,
            policy=policy,
        )


def test_unresolved_publication_authorization_excludes_observation_from_selection(
    db_session,
) -> None:
    """With no policy decision recorded at all, `STORE`/`DISPLAY`/
    `REDISTRIBUTE` default to `UNRESOLVED`: the observation exists but
    is not selectable (specs/source-governance/spec.md § "Evidence and
    review": `APPROVED` is never inferred from technical access).
    """

    listing = _make_listing(db_session)
    store = ObservationStore(db_session)
    _record(store, listing.id, source="unresolved-source", close="100.00")

    selector = ObservationSelector(db_session)
    policy = SourcePriorityPolicy(name="unresolved-first", ordered_sources=("unresolved-source",))

    with pytest.raises(NoEligibleObservationError):
        selector.select(
            listing_id=listing.id,
            session_date=SESSION_DATE,
            observation_type=ObservationType.EOD_CLOSE,
            policy=policy,
        )


def test_revoked_publication_authorization_excludes_observation_dynamically(db_session) -> None:
    """Revoking a source's publication authorization SHALL apply
    immediately to selection without mutating any `Observation` row
    (specs/market-observations/spec.md § "Preserved history";
    `ObservationStore.revoke_publishability` was removed because it did
    exactly that, an `UPDATE` over the append-only history). Here the
    "revocation" is a new `DENIED` version of `REDISTRIBUTE` recorded in
    `PolicyGate`, which never overwrites the previous version.
    """

    listing = _make_listing(db_session)
    store = ObservationStore(db_session)
    observation = _record(store, listing.id, source="revoked-source", close="100.00")
    _authorize_publication(db_session, "revoked-source")

    selector = ObservationSelector(db_session)
    policy = SourcePriorityPolicy(name="revoked-first", ordered_sources=("revoked-source",))

    # Before revocation, the observation is selectable.
    result = selector.select(
        listing_id=listing.id,
        session_date=SESSION_DATE,
        observation_type=ObservationType.EOD_CLOSE,
        policy=policy,
    )
    assert result.selected.id == observation.id

    gate = PolicyGate(db_session)
    gate.record_decision(
        source="revoked-source",
        capability=PolicyCapability.REDISTRIBUTE,
        status=PolicyStatus.DENIED,
        evidence_reference="https://revoked-source.example/terms/v2",
        reviewed_by="ops@holdria.test",
    )

    with pytest.raises(NoEligibleObservationError):
        selector.select(
            listing_id=listing.id,
            session_date=SESSION_DATE,
            observation_type=ObservationType.EOD_CLOSE,
            policy=policy,
        )

    # The original row remains intact and unaltered: revocation never touched it.
    unchanged = db_session.get(Observation, observation.id)
    assert unchanged is not None
    assert unchanged.close == Decimal("100.00")
    assert unchanged.source == "revoked-source"


def test_selection_uses_latest_revision_after_correction(db_session) -> None:
    listing = _make_listing(db_session)
    store = ObservationStore(db_session)
    _record(store, listing.id, source="primary", close="100.00")
    _record(store, listing.id, source="primary", close="103.00")  # correction: revision 2
    _authorize_publication(db_session, "primary")

    selector = ObservationSelector(db_session)
    policy = SourcePriorityPolicy(name="primary-first", ordered_sources=("primary",))
    result = selector.select(
        listing_id=listing.id,
        session_date=SESSION_DATE,
        observation_type=ObservationType.EOD_CLOSE,
        policy=policy,
    )

    assert result.selected.close == Decimal("103.00")
    assert result.selected.revision == 2
