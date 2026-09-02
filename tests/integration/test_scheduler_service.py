"""Single scheduler: bounded refresh, dispatch and processing (tasks.md 6.1;
design.md § "Single scheduler with persistent queue"; specs/operations/spec.md
§ "Portable scheduled entry point"). Only the deterministic `fake`
adapter is used: no real source or network is instantiated in this test.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from sqlalchemy.orm import Session

from market_relay.config import Settings
from market_relay.domain.catalog import AssetClass, CatalogService
from market_relay.domain.governance import PolicyCapability, PolicyGate, PolicyStatus
from market_relay.domain.ingestion import scheduler_service
from market_relay.domain.ingestion.error_codes import ADAPTER_ERROR
from market_relay.domain.ingestion.metrics import collect_scheduler_metrics
from market_relay.domain.ingestion.planning import RecoveryLimits
from market_relay.domain.ingestion.scheduler_service import run_scheduler_cycle
from market_relay.domain.observations.models import (
    Job,
    Observation,
    SchedulerRun,
    SchedulerRunStatus,
)

NOW = datetime(2026, 1, 9, 10, 0, tzinfo=UTC)
# Short range so the test completes a whole cycle in a single execution,
# regardless of the scheduler's batch size.
LIMITS = RecoveryLimits(max_lookback_days=10, max_sessions_per_chunk=5)


def _approve_ingestion(session: Session, source: str = "fake") -> None:
    gate = PolicyGate(session)
    for capability in (PolicyCapability.RETRIEVE, PolicyCapability.STORE):
        gate.record_decision(
            source=source,
            capability=capability,
            status=PolicyStatus.APPROVED,
            evidence_reference=f"https://{source}.example/terms#{capability.value.lower()}",
            reviewed_by="ops@holdria.test",
        )


def _setup_listing(session: Session) -> None:
    catalog = CatalogService(session)
    instrument = catalog.register_instrument(
        asset_class=AssetClass.EQUITY, name="SAP SE", isin="DE0007164600"
    )
    listing = catalog.add_listing(
        instrument=instrument, venue="XETR", mic="XETR", ticker="SAP", currency="EUR"
    )
    catalog.link_external_identity(
        listing=listing, source="fake", external_id="FAKE-SAP", valid_from=date(2025, 1, 1)
    )
    session.commit()


def test_running_the_cycle_twice_does_not_duplicate_jobs_or_observations(
    db_session: Session,
) -> None:
    """Requirement 6.1 and the "Successful periodic execution" scenario: the
    entry point completes bounded phases and can be re-run without
    duplicate effects.
    """

    _setup_listing(db_session)
    _approve_ingestion(db_session)
    settings = Settings(enabled_sources=("fake",), scheduler_batch_size=50)

    first = run_scheduler_cycle(
        session=db_session,
        settings=settings,
        now=NOW,
        max_listings_per_source=10,
        recovery_limits=LIMITS,
    )
    db_session.commit()

    assert first.refresh.jobs_enqueued > 0
    assert first.processed.jobs_done > 0
    assert first.processed.jobs_failed_terminal == 0

    jobs_after_first = db_session.query(Job).count()
    observations_after_first = db_session.query(Observation).count()
    assert observations_after_first > 0

    second = run_scheduler_cycle(
        session=db_session,
        settings=settings,
        now=NOW,
        max_listings_per_source=10,
        recovery_limits=LIMITS,
    )
    db_session.commit()

    # The pending range was already covered by the first cycle: the second
    # one finds no further recovery to dispatch and no pending job to
    # claim, so neither `jobs` nor `observations` gains a new row.
    assert second.refresh.jobs_enqueued == 0
    assert second.processed.jobs_claimed == 0
    assert db_session.query(Job).count() == jobs_after_first
    assert db_session.query(Observation).count() == observations_after_first


def test_re_dispatching_after_a_lost_confirmation_does_not_duplicate_the_job(
    db_session: Session,
) -> None:
    """A `PENDING` job re-dispatched after a lost orchestrator confirmation
    SHALL remain the same row (same `dedupe_key`), not a new one, even when
    `refresh_and_dispatch` runs again before the original job completes.
    """

    from market_relay.domain.ingestion.scheduler_service import refresh_and_dispatch

    _setup_listing(db_session)
    _approve_ingestion(db_session)
    settings = Settings(enabled_sources=("fake",), scheduler_batch_size=50)

    refresh_and_dispatch(
        session=db_session,
        settings=settings,
        now=NOW,
        max_listings_per_source=10,
        recovery_limits=LIMITS,
    )
    db_session.commit()
    jobs_after_first_dispatch = db_session.query(Job).count()
    assert jobs_after_first_dispatch > 0

    # Re-run the refresh before anything completes: dispatch SHALL be
    # idempotent even when no job has finished yet.
    refresh_and_dispatch(
        session=db_session,
        settings=settings,
        now=NOW,
        max_listings_per_source=10,
        recovery_limits=LIMITS,
    )
    db_session.commit()

    assert db_session.query(Job).count() == jobs_after_first_dispatch


def test_a_successful_cycle_records_a_durable_run_with_both_phases_succeeding(
    db_session: Session,
) -> None:
    """tasks.md 6.1; specs/operations/spec.md § "Minimum observability":
    a `scheduler_runs` row backs the "successful scheduler and worker
    execution" signal independently of individual job outcomes.
    """

    _setup_listing(db_session)
    _approve_ingestion(db_session)
    settings = Settings(enabled_sources=("fake",), scheduler_batch_size=50)

    run_scheduler_cycle(
        session=db_session,
        settings=settings,
        now=NOW,
        max_listings_per_source=10,
        recovery_limits=LIMITS,
    )

    runs = db_session.query(SchedulerRun).all()
    assert len(runs) == 1
    assert runs[0].scheduler_status is SchedulerRunStatus.SUCCESS
    assert runs[0].worker_status is SchedulerRunStatus.SUCCESS
    assert runs[0].error_code is None
    assert runs[0].finished_at is not None

    snapshot = collect_scheduler_metrics(
        session=db_session, now=NOW, stalled_threshold_seconds=3600, sources=("fake",)
    )
    assert snapshot.scheduler_success_count == 1
    assert snapshot.worker_success_count == 1


def test_repeated_successful_cycles_each_add_a_durable_success_run(db_session: Session) -> None:
    """Requirement 6.1's "successful periodic execution": each re-run of the
    entry point contributes its own durable success signal, so the counts
    grow with every execution, not just the first one.
    """

    _setup_listing(db_session)
    _approve_ingestion(db_session)
    settings = Settings(enabled_sources=("fake",), scheduler_batch_size=50)

    for _ in range(3):
        run_scheduler_cycle(
            session=db_session,
            settings=settings,
            now=NOW,
            max_listings_per_source=10,
            recovery_limits=LIMITS,
        )

    assert db_session.query(SchedulerRun).count() == 3
    snapshot = collect_scheduler_metrics(
        session=db_session, now=NOW, stalled_threshold_seconds=3600, sources=("fake",)
    )
    assert snapshot.scheduler_success_count == 3
    assert snapshot.worker_success_count == 3


def test_a_systemic_refresh_failure_is_recorded_as_a_failed_run_and_the_worker_phase_never_runs(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failure escaping `refresh_and_dispatch`'s own per-source isolation
    (a systemic failure, not one isolated to a single source or listing)
    SHALL still leave a durable, generic failure record — never silently
    disappear along with the rolled-back work, and never carry the
    exception's own text (tasks.md 6.1, 6.2).
    """

    _setup_listing(db_session)
    _approve_ingestion(db_session)
    settings = Settings(enabled_sources=("fake",), scheduler_batch_size=50)

    def _broken_refresh(**_kwargs: object) -> None:
        raise RuntimeError("simulated systemic failure: sk_live_DECOY_should_never_leak")

    monkeypatch.setattr(scheduler_service, "refresh_and_dispatch", _broken_refresh)

    with pytest.raises(RuntimeError):
        run_scheduler_cycle(
            session=db_session,
            settings=settings,
            now=NOW,
            max_listings_per_source=10,
            recovery_limits=LIMITS,
        )

    runs = db_session.query(SchedulerRun).all()
    assert len(runs) == 1
    assert runs[0].scheduler_status is SchedulerRunStatus.FAILURE
    assert runs[0].worker_status is SchedulerRunStatus.FAILURE
    assert runs[0].error_code == ADAPTER_ERROR
    assert "sk_live_DECOY_should_never_leak" not in (runs[0].error_code or "")


def test_a_systemic_processing_failure_never_erases_the_already_recorded_refresh_success(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The refresh phase's own durable success record SHALL survive a
    failure in the later processing phase: the two phases are committed and
    recorded independently (tasks.md 6.1).
    """

    _setup_listing(db_session)
    _approve_ingestion(db_session)
    settings = Settings(enabled_sources=("fake",), scheduler_batch_size=50)

    def _broken_process(**_kwargs: object) -> None:
        raise RuntimeError("simulated systemic failure")

    monkeypatch.setattr(scheduler_service, "claim_and_process", _broken_process)

    with pytest.raises(RuntimeError):
        run_scheduler_cycle(
            session=db_session,
            settings=settings,
            now=NOW,
            max_listings_per_source=10,
            recovery_limits=LIMITS,
        )

    runs = db_session.query(SchedulerRun).all()
    assert len(runs) == 1
    assert runs[0].scheduler_status is SchedulerRunStatus.SUCCESS
    assert runs[0].worker_status is SchedulerRunStatus.FAILURE
    assert runs[0].error_code == ADAPTER_ERROR
    # The refresh phase's own dispatched jobs were already committed before
    # the processing phase failed: the rollback of the failed phase never
    # touches that already-durable work.
    assert db_session.query(Job).count() > 0
