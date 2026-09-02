"""Operational degradation and recovery (tasks.md 6.3;
specs/operations/spec.md § "Safe degraded operation"): a down source, one
with no quota, or one returning malformed responses SHALL degrade only its
own jobs, never another source's nor already-publishable history, and a
source that recovers SHALL go back to completing its pending work without
manual intervention. All adapters used here are deterministic fakes
registered only for this test; no real source or network is instantiated.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from market_relay.adapters import registry
from market_relay.adapters.fake.provider import FakeMarketDataProvider, FakeQuotaBook
from market_relay.config import Settings
from market_relay.domain.catalog import AssetClass, CatalogService
from market_relay.domain.governance import PolicyCapability, PolicyGate, PolicyStatus
from market_relay.domain.ingestion.metrics import collect_scheduler_metrics
from market_relay.domain.ingestion.planning import RecoveryLimits
from market_relay.domain.ingestion.queue import JobQueue
from market_relay.domain.ingestion.scheduler_service import (
    DEFAULT_CREDENTIAL_SCOPE,
    claim_and_process,
    refresh_and_dispatch,
)
from market_relay.domain.observations.models import (
    Observation,
    ObservationType,
    QualityStatus,
)
from market_relay.domain.observations.service import ObservationInput, ObservationStore
from market_relay.ports.historical import RawObservation

NOW = datetime(2026, 1, 9, 10, 0, tzinfo=UTC)
LIMITS = RecoveryLimits(max_lookback_days=10, max_sessions_per_chunk=5)


class FailingProvider(FakeMarketDataProvider):
    """Fake adapter that simulates a down source: calendar and quota
    work normally (deterministic, no network), but `fetch_range`
    fails while `fail` is `True` — enough to exercise failure
    isolation and recovery without any real adapter.
    """

    def __init__(self, *, fail: bool = True, quota_book: FakeQuotaBook | None = None) -> None:
        super().__init__(quota_book=quota_book)
        self.fail = fail

    def fetch_range(
        self, *, external_listing_id: str, start: date, end: date
    ) -> list[RawObservation]:
        if self.fail:
            raise RuntimeError("simulated 'broken' provider: transient test failure")
        return super().fetch_range(external_listing_id=external_listing_id, start=start, end=end)


def _approve_ingestion(session: Session, source: str) -> None:
    gate = PolicyGate(session)
    for capability in (PolicyCapability.RETRIEVE, PolicyCapability.STORE):
        gate.record_decision(
            source=source,
            capability=capability,
            status=PolicyStatus.APPROVED,
            evidence_reference=f"https://{source}.example/terms#{capability.value.lower()}",
            reviewed_by="ops@holdria.test",
        )


def _listing(session: Session, *, ticker: str, isin: str, source: str, external_id: str):
    catalog = CatalogService(session)
    instrument = catalog.register_instrument(asset_class=AssetClass.EQUITY, name=ticker, isin=isin)
    listing = catalog.add_listing(
        instrument=instrument, venue="XETR", mic="XETR", ticker=ticker, currency="EUR"
    )
    catalog.link_external_identity(
        listing=listing, source=source, external_id=external_id, valid_from=date(2025, 1, 1)
    )
    session.commit()
    return listing


def _run_cycle(session: Session, settings: Settings, now: datetime) -> None:
    refresh_and_dispatch(
        session=session,
        settings=settings,
        now=now,
        max_listings_per_source=10,
        recovery_limits=LIMITS,
    )
    claim_and_process(
        session=session, settings=settings, now=now, batch_size=settings.scheduler_batch_size
    )
    session.commit()


def test_one_source_failing_does_not_affect_another_source_or_its_history(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    healthy_listing = _listing(
        db_session, ticker="SAP", isin="DE0007164600", source="fake", external_id="FAKE-SAP"
    )
    broken_listing = _listing(
        db_session, ticker="BRK", isin="DE0007164601", source="broken", external_id="BROKEN-BRK"
    )
    _approve_ingestion(db_session, "fake")
    _approve_ingestion(db_session, "broken")

    monkeypatch.setitem(registry._ADAPTERS, "broken", FailingProvider(fail=True))

    # History already published before "broken" starts failing: SHALL
    # remain available no matter what happens to "broken" afterward
    # (specs/operations/spec.md § "A source stops responding").
    store = ObservationStore(db_session)
    store.record(
        ObservationInput(
            listing_id=broken_listing.id,
            source="broken",
            credential_scope=DEFAULT_CREDENTIAL_SCOPE,
            external_listing_id="BROKEN-BRK",
            session_date=date(2026, 1, 2),
            observation_type=ObservationType.EOD_CLOSE,
            currency="EUR",
            close=Decimal("42.00"),
            retrieved_at=NOW,
            quality_status=QualityStatus.OK,
        )
    )
    db_session.commit()

    settings = Settings(enabled_sources=("fake", "broken"), scheduler_batch_size=50)

    now = NOW
    # Bounded backoff (max 3600s): advancing 2h per cycle is enough for
    # each "broken" retry to become eligible again, until it exhausts its
    # default 5 attempts and ends up `FAILED` (terminal).
    for _ in range(6):
        _run_cycle(db_session, settings, now)
        now += timedelta(hours=2)

    queue = JobQueue(db_session)
    failed_by_source = queue.failed_by_source()
    assert failed_by_source.get("broken", 0) >= 1
    assert failed_by_source.get("fake", 0) == 0

    # "fake" kept ingesting normally even while "broken" was failing in
    # parallel.
    fake_rows = (
        db_session.query(Observation)
        .filter(Observation.listing_id == healthy_listing.id, Observation.source == "fake")
        .all()
    )
    assert len(fake_rows) > 0

    # "broken"'s prior history remains intact, neither mutated nor deleted.
    preexisting = store.current_for_key(
        source="broken",
        credential_scope=DEFAULT_CREDENTIAL_SCOPE,
        external_listing_id="BROKEN-BRK",
        session_date=date(2026, 1, 2),
        observation_type=ObservationType.EOD_CLOSE,
    )
    assert preexisting is not None
    assert preexisting.close == Decimal("42.00")

    # No new observation slipped in for "broken" despite the retries.
    broken_new_rows = (
        db_session.query(Observation)
        .filter(
            Observation.listing_id == broken_listing.id,
            Observation.session_date != date(2026, 1, 2),
        )
        .all()
    )
    assert broken_new_rows == []


def test_transient_failure_recovers_after_backoff_retry(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """specs/operations/spec.md § "A source stops responding": when the
    source responds again, recovery correctly retries with no manual
    intervention and no duplicate observations.
    """

    listing = _listing(
        db_session, ticker="BRK", isin="DE0007164602", source="broken", external_id="BROKEN-BRK-2"
    )
    _approve_ingestion(db_session, "broken")

    failing_provider = FailingProvider(fail=True)
    monkeypatch.setitem(registry._ADAPTERS, "broken", failing_provider)

    settings = Settings(enabled_sources=("broken",), scheduler_batch_size=50)

    now = NOW
    _run_cycle(db_session, settings, now)  # dispatches and fails the first attempt

    queue = JobQueue(db_session)
    assert queue.failed_by_source().get("broken", 0) == 0  # has not exhausted max_attempts yet
    pending_after_first_failure = queue.pending_by_source().get("broken", 0)
    assert pending_after_first_failure > 0

    # The source recovers before exhausting retries.
    failing_provider.fail = False
    now += timedelta(hours=2)  # exceeds the first failure's bounded backoff
    _run_cycle(db_session, settings, now)

    assert queue.failed_by_source().get("broken", 0) == 0
    assert queue.pending_by_source().get("broken", 0) == 0  # all pending work completed
    rows = db_session.query(Observation).filter(Observation.listing_id == listing.id).all()
    assert len(rows) > 0
    assert len(rows) == len({(row.session_date, row.external_listing_id) for row in rows})


def test_quota_exhausted_source_does_not_affect_healthy_source(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    healthy_listing = _listing(
        db_session, ticker="SAP", isin="DE0007164603", source="fake", external_id="FAKE-SAP-3"
    )
    exhausted_listing = _listing(
        db_session,
        ticker="NOQ",
        isin="DE0007164604",
        source="no-quota",
        external_id="NOQ-EXTERNAL",
    )
    _approve_ingestion(db_session, "fake")
    _approve_ingestion(db_session, "no-quota")

    monkeypatch.setitem(
        registry._ADAPTERS, "no-quota", FakeMarketDataProvider(quota_book=FakeQuotaBook(limit=0))
    )

    settings = Settings(enabled_sources=("fake", "no-quota"), scheduler_batch_size=50)
    _run_cycle(db_session, settings, NOW)

    queue = JobQueue(db_session)
    # Quota exhausted: deferred without counting as a failure or blocking "fake".
    assert queue.failed_by_source().get("no-quota", 0) == 0
    assert queue.pending_by_source().get("no-quota", 0) >= 1

    fake_rows = (
        db_session.query(Observation)
        .filter(Observation.listing_id == healthy_listing.id, Observation.source == "fake")
        .all()
    )
    assert len(fake_rows) > 0
    exhausted_rows = (
        db_session.query(Observation).filter(Observation.listing_id == exhausted_listing.id).all()
    )
    assert exhausted_rows == []

    snapshot = collect_scheduler_metrics(
        session=db_session, now=NOW, stalled_threshold_seconds=3600, sources=("fake", "no-quota")
    )
    by_source = {quota.source: quota for quota in snapshot.quota_by_source}
    assert by_source["no-quota"].exhausted is True
    assert by_source["fake"].exhausted is False


def test_malformed_source_does_not_affect_healthy_source(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    healthy_listing = _listing(
        db_session, ticker="SAP", isin="DE0007164605", source="fake", external_id="FAKE-SAP-4"
    )
    malformed_listing = _listing(
        db_session,
        ticker="MAL",
        isin="DE0007164606",
        source="malformed",
        external_id="MALFORMED-EXTERNAL",
    )
    _approve_ingestion(db_session, "fake")
    _approve_ingestion(db_session, "malformed")

    malformed_provider = FakeMarketDataProvider()

    def _malformed_fetch(
        *, external_listing_id: str, start: date, end: date
    ) -> list[RawObservation]:
        return [
            RawObservation(
                external_listing_id=external_listing_id,
                session_date=start,
                observation_type=ObservationType.EOD_CLOSE,
                currency="EURX",  # invalid currency: forces MalformedObservationError
                close=Decimal("10.00"),
            )
        ]

    malformed_provider.fetch_range = _malformed_fetch  # type: ignore[method-assign]
    monkeypatch.setitem(registry._ADAPTERS, "malformed", malformed_provider)

    settings = Settings(enabled_sources=("fake", "malformed"), scheduler_batch_size=50)
    _run_cycle(db_session, settings, NOW)

    fake_rows = (
        db_session.query(Observation)
        .filter(Observation.listing_id == healthy_listing.id, Observation.source == "fake")
        .all()
    )
    assert len(fake_rows) > 0
    malformed_rows = (
        db_session.query(Observation).filter(Observation.listing_id == malformed_listing.id).all()
    )
    assert malformed_rows == []

    queue = JobQueue(db_session)
    # Bounded, non-blocking retry: the malformed job remains
    # `PENDING`, not `FAILED`, after a single attempt.
    assert queue.pending_by_source().get("malformed", 0) >= 1
