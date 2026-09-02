"""Ingestion integration: recovery, queue, quota and failure isolation
with `FakeMarketDataProvider` (tasks.md 4.4, 4.5). No real source
is instantiated in this test.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from market_relay.adapters.fake.provider import FakeMarketDataProvider, FakeQuotaBook
from market_relay.domain.catalog import AssetClass, CatalogService
from market_relay.domain.catalog.models import Listing
from market_relay.domain.governance import PolicyCapability, PolicyGate, PolicyStatus
from market_relay.domain.ingestion import (
    IngestionRunner,
    JobQueue,
    RecoveryLimits,
    plan_and_enqueue,
)
from market_relay.domain.ingestion.queue import StaleJobClaimError
from market_relay.domain.observations import ObservationStore
from market_relay.domain.observations.models import JobStatus, ObservationType
from market_relay.ports.historical import RawObservation

NOW = datetime(2026, 1, 9, 23, 0, tzinfo=UTC)


def _approved_gate(session: Session, source: str = "fake") -> PolicyGate:
    gate = PolicyGate(session)
    for capability in (
        PolicyCapability.RETRIEVE,
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
    return gate


def _setup_listing(session: Session) -> Listing:
    catalog = CatalogService(session)
    instrument = catalog.register_instrument(
        asset_class=AssetClass.EQUITY, name="SAP SE", isin="DE0007164600"
    )
    listing = catalog.add_listing(
        instrument=instrument, venue="XETR", mic="XETR", ticker="SAP", currency="EUR"
    )
    catalog.link_external_identity(
        listing=listing,
        source="fake",
        external_id="FAKE-DE0007164600-XETR",
        valid_from=date(2025, 1, 1),
    )
    session.commit()
    return listing


def test_multiple_missed_sessions_are_recovered_and_recorded(db_session) -> None:
    """Requirement 4.4: several missing sessions are recovered in bounded
    jobs and each one produces a persisted observation.
    """

    listing = _setup_listing(db_session)
    gate = _approved_gate(db_session)
    retrieval_decision = gate.effective_decision("fake", PolicyCapability.RETRIEVE)
    storage_decision = gate.effective_decision("fake", PolicyCapability.STORE)
    assert retrieval_decision is not None and storage_decision is not None
    provider = FakeMarketDataProvider()
    queue = JobQueue(db_session)
    store = ObservationStore(db_session)

    dispatch = plan_and_enqueue(
        queue=queue,
        calendar=provider,
        limits=RecoveryLimits(max_lookback_days=30, max_sessions_per_chunk=3),
        listing_id=listing.id,
        asset_class=AssetClass.EQUITY,
        venue="XETR",
        mic="XETR",
        source="fake",
        credential_scope="default",
        external_listing_id="FAKE-DE0007164600-XETR",
        observation_type=ObservationType.EOD_CLOSE,
        last_completed_session=date(2025, 12, 29),
        today=date(2026, 1, 9),
        now=NOW,
    )
    assert dispatch.plan.total_expected_sessions == 9
    assert len(dispatch.enqueued) == len(dispatch.plan.chunks)

    runner = IngestionRunner(provider=provider, policy_gate=gate, queue=queue, store=store)

    total_recorded = 0
    for enqueue_result in dispatch.enqueued:
        outcome = runner.process(enqueue_result.job, worker_id="worker-1", now=NOW)
        assert outcome.detail == "done"
        total_recorded += outcome.observations_recorded

    assert total_recorded == dispatch.plan.total_expected_sessions

    db_session.commit()
    for chunk in dispatch.plan.chunks:
        for session_date in chunk.session_dates:
            observation = store.current_for_key(
                source="fake",
                credential_scope="default",
                external_listing_id="FAKE-DE0007164600-XETR",
                session_date=session_date,
                observation_type=ObservationType.EOD_CLOSE,
            )
            assert observation is not None
            assert observation.retrieval_policy_decision_id == retrieval_decision.id
            assert observation.storage_policy_decision_id == storage_decision.id
            assert observation.listing_id == listing.id
            assert observation.listing.instrument_id == listing.instrument_id


def test_rerunning_a_done_job_is_safe_and_does_not_duplicate(db_session) -> None:
    listing = _setup_listing(db_session)
    gate = _approved_gate(db_session)
    provider = FakeMarketDataProvider()
    queue = JobQueue(db_session)
    store = ObservationStore(db_session)
    runner = IngestionRunner(provider=provider, policy_gate=gate, queue=queue, store=store)

    dispatch = plan_and_enqueue(
        queue=queue,
        calendar=provider,
        limits=RecoveryLimits(max_lookback_days=30, max_sessions_per_chunk=10),
        listing_id=listing.id,
        asset_class=AssetClass.EQUITY,
        venue="XETR",
        mic="XETR",
        source="fake",
        credential_scope="default",
        external_listing_id="FAKE-DE0007164600-XETR",
        observation_type=ObservationType.EOD_CLOSE,
        last_completed_session=date(2026, 1, 4),
        today=date(2026, 1, 5),
        now=NOW,
    )
    job = dispatch.enqueued[0].job

    first = runner.process(job, worker_id="worker-1", now=NOW)
    with pytest.raises(StaleJobClaimError):
        runner.process(job, worker_id="worker-1", now=NOW)

    # The first run creates the observation; re-running recognizes it as
    # already completed and the fenced queue rejects a stale replay.
    assert first.observations_recorded == 1

    from market_relay.domain.observations.models import Observation

    db_session.commit()
    rows = db_session.query(Observation).all()
    assert len(rows) == 1


def test_retrieve_approved_but_store_unresolved_blocks_fetch_and_persistence(
    db_session, monkeypatch
) -> None:
    """specs/source-governance/spec.md § 'Policy-governed activation':
    ingestion requires RETRIEVE *and* STORE. With STORE unresolved,
    neither the provider is called nor is any observation persisted, and
    the error is sanitized.
    """

    listing = _setup_listing(db_session)
    gate = PolicyGate(db_session)
    gate.record_decision(
        source="fake",
        capability=PolicyCapability.RETRIEVE,
        status=PolicyStatus.APPROVED,
        evidence_reference="https://fake.example/terms#retrieve",
        reviewed_by="ops@holdria.test",
    )
    # STORE is never recorded: it stays UNRESOLVED by default.
    provider = FakeMarketDataProvider()
    queue = JobQueue(db_session)
    store = ObservationStore(db_session)
    runner = IngestionRunner(provider=provider, policy_gate=gate, queue=queue, store=store)

    calls: list[str] = []
    original_fetch = provider.fetch_range

    def _tracked_fetch(**kwargs: object) -> list[object]:
        calls.append("called")
        return list(original_fetch(**kwargs))  # type: ignore[arg-type]

    monkeypatch.setattr(provider, "fetch_range", _tracked_fetch)

    dispatch = plan_and_enqueue(
        queue=queue,
        calendar=provider,
        limits=RecoveryLimits(max_lookback_days=5, max_sessions_per_chunk=10),
        listing_id=listing.id,
        asset_class=AssetClass.EQUITY,
        venue="XETR",
        mic="XETR",
        source="fake",
        credential_scope="default",
        external_listing_id="FAKE-DE0007164600-XETR",
        observation_type=ObservationType.EOD_CLOSE,
        last_completed_session=date(2026, 1, 4),
        today=date(2026, 1, 5),
        now=NOW,
    )
    job = dispatch.enqueued[0].job

    outcome = runner.process(job, worker_id="worker-1", now=NOW)

    assert outcome.detail == "policy_not_authorized"
    assert calls == []  # the provider was never called
    assert outcome.observations_recorded == 0
    assert job.status == JobStatus.PENDING  # bounded retry, not immediately FAILED

    db_session.commit()
    from market_relay.domain.observations.models import Observation

    assert db_session.query(Observation).count() == 0
    # The recorded failure is sanitized: it does not include the source
    # name concatenated with secrets, but does include the blocking
    # capability's detail.
    assert job.last_error is not None
    assert "STORE" in job.last_error


def test_quota_exhausted_defers_without_calling_provider_fetch(db_session, monkeypatch) -> None:
    """specs/market-data-ingestion/spec.md § 'Quota exhausted': the job is
    deferred without making any further useless request.
    """

    listing = _setup_listing(db_session)
    gate = _approved_gate(db_session)
    exhausted_book = FakeQuotaBook(limit=0)
    provider = FakeMarketDataProvider(quota_book=exhausted_book)
    queue = JobQueue(db_session)
    store = ObservationStore(db_session)
    runner = IngestionRunner(provider=provider, policy_gate=gate, queue=queue, store=store)

    calls: list[str] = []
    original_fetch = provider.fetch_range

    def _tracked_fetch(**kwargs: object) -> list[object]:
        calls.append("called")
        return list(original_fetch(**kwargs))  # type: ignore[arg-type]

    monkeypatch.setattr(provider, "fetch_range", _tracked_fetch)

    dispatch = plan_and_enqueue(
        queue=queue,
        calendar=provider,
        limits=RecoveryLimits(max_lookback_days=5, max_sessions_per_chunk=10),
        listing_id=listing.id,
        asset_class=AssetClass.EQUITY,
        venue="XETR",
        mic="XETR",
        source="fake",
        credential_scope="default",
        external_listing_id="FAKE-DE0007164600-XETR",
        observation_type=ObservationType.EOD_CLOSE,
        last_completed_session=date(2026, 1, 4),
        today=date(2026, 1, 5),
        now=NOW,
    )
    job = dispatch.enqueued[0].job

    outcome = runner.process(job, worker_id="worker-1", now=NOW)

    assert outcome.detail == "quota_exhausted"
    assert calls == []  # no further recovery call
    assert job.status == JobStatus.PENDING
    assert job.attempt_count == 0
    assert job.next_run_at.replace(tzinfo=UTC) > NOW


def test_malformed_observation_is_isolated_and_does_not_stop_other_jobs(db_session) -> None:
    """specs/market-data-ingestion/spec.md § 'Malformed response': the
    invalid observation is rejected without affecting other jobs.
    """

    listing = _setup_listing(db_session)
    gate = _approved_gate(db_session)
    provider = FakeMarketDataProvider()
    queue = JobQueue(db_session)
    store = ObservationStore(db_session)
    runner = IngestionRunner(provider=provider, policy_gate=gate, queue=queue, store=store)

    dispatch = plan_and_enqueue(
        queue=queue,
        calendar=provider,
        limits=RecoveryLimits(max_lookback_days=5, max_sessions_per_chunk=10),
        listing_id=listing.id,
        asset_class=AssetClass.EQUITY,
        venue="XETR",
        mic="XETR",
        source="fake",
        credential_scope="default",
        external_listing_id="FAKE-DE0007164600-XETR",
        observation_type=ObservationType.EOD_CLOSE,
        last_completed_session=date(2026, 1, 4),
        today=date(2026, 1, 6),
        now=NOW,
    )
    bad_job = dispatch.enqueued[0].job

    def _malformed_fetch(
        *, external_listing_id: str, start: date, end: date
    ) -> list[RawObservation]:
        return [
            RawObservation(
                external_listing_id=external_listing_id,
                session_date=start,
                observation_type=ObservationType.EOD_CLOSE,
                currency="EURX",  # invalid currency: triggers MalformedObservationError
                close=Decimal("10.00"),
            )
        ]

    provider.fetch_range = _malformed_fetch  # type: ignore[method-assign]

    outcome = runner.process(bad_job, worker_id="worker-1", now=NOW)
    assert outcome.detail == "all_malformed"
    assert bad_job.status == JobStatus.PENDING  # bounded, non-blocking retry

    # A second job (another simulated instrument) with the original
    # deterministic provider keeps working normally.
    healthy_provider = FakeMarketDataProvider()
    healthy_runner = IngestionRunner(
        provider=healthy_provider, policy_gate=gate, queue=queue, store=store
    )
    other_dispatch = plan_and_enqueue(
        queue=queue,
        calendar=healthy_provider,
        limits=RecoveryLimits(max_lookback_days=5, max_sessions_per_chunk=10),
        listing_id=listing.id,
        asset_class=AssetClass.EQUITY,
        venue="XETR",
        mic="XETR",
        source="fake",
        credential_scope="secondary-scope",
        external_listing_id="FAKE-DE0007164600-XETR",
        observation_type=ObservationType.EOD_CLOSE,
        last_completed_session=date(2026, 1, 4),
        today=date(2026, 1, 6),
        now=NOW,
    )
    healthy_job = other_dispatch.enqueued[0].job
    healthy_outcome = healthy_runner.process(healthy_job, worker_id="worker-2", now=NOW)
    assert healthy_outcome.detail == "done"
    assert healthy_outcome.observations_recorded > 0
