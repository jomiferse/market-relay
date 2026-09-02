"""Real concurrency of the single scheduler: several bounded workers share
the queue without claiming the same job twice or producing duplicate
observations (tasks.md 6.1; design.md § "Single scheduler with persistent
queue" requires atomic locks/claims valid for a single scheduler and
concurrent workers). Only the deterministic `fake` adapter is used here.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime

from market_relay.config import Settings
from market_relay.domain.catalog import AssetClass, CatalogService
from market_relay.domain.governance import PolicyCapability, PolicyGate, PolicyStatus
from market_relay.domain.ingestion.planning import RecoveryLimits
from market_relay.domain.ingestion.scheduler_service import claim_and_process, refresh_and_dispatch
from market_relay.domain.observations.models import Job, JobStatus, Observation

NOW = datetime(2026, 1, 9, 10, 0, tzinfo=UTC)
# Small chunks to produce several independent jobs to distribute
# among concurrent workers.
LIMITS = RecoveryLimits(max_lookback_days=15, max_sessions_per_chunk=3)


def test_concurrent_bounded_workers_never_double_process_a_dispatched_job(session_factory) -> None:
    setup = session_factory()
    try:
        catalog = CatalogService(setup)
        instrument = catalog.register_instrument(
            asset_class=AssetClass.EQUITY, name="SAP SE", isin="DE0007164600"
        )
        listing = catalog.add_listing(
            instrument=instrument, venue="XETR", mic="XETR", ticker="SAP", currency="EUR"
        )
        catalog.link_external_identity(
            listing=listing, source="fake", external_id="FAKE-SAP", valid_from=date(2025, 1, 1)
        )
        gate = PolicyGate(setup)
        for capability in (PolicyCapability.RETRIEVE, PolicyCapability.STORE):
            gate.record_decision(
                source="fake",
                capability=capability,
                status=PolicyStatus.APPROVED,
                evidence_reference="https://fake.example/terms#ingestion",
                reviewed_by="ops@holdria.test",
            )
        setup.commit()

        settings = Settings(enabled_sources=("fake",), scheduler_batch_size=50)
        refresh_and_dispatch(
            session=setup,
            settings=settings,
            now=NOW,
            max_listings_per_source=10,
            recovery_limits=LIMITS,
        )
        setup.commit()

        pending_before = setup.query(Job).filter(Job.status == JobStatus.PENDING).count()
        assert pending_before > 1  # we need several jobs to distribute among workers
    finally:
        setup.close()

    def worker(worker_id: str) -> int:
        session = session_factory()
        try:
            outcome = claim_and_process(
                session=session,
                settings=settings,
                now=NOW,
                batch_size=pending_before,
                worker_id=worker_id,
            )
            session.commit()
            return outcome.jobs_claimed
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=4) as executor:
        claimed_counts = list(executor.map(worker, [f"scheduler-worker-{i}" for i in range(4)]))

    # Each dispatched job is processed by at most one worker; the sum of
    # what all of them claimed matches exactly what was pending.
    assert sum(claimed_counts) == pending_before

    verify = session_factory()
    try:
        jobs = verify.query(Job).all()
        assert all(job.status == JobStatus.DONE for job in jobs)

        rows = [
            (obs.external_listing_id, obs.session_date, obs.observation_type)
            for obs in verify.query(Observation).all()
        ]
        assert len(rows) == len(set(rows))  # no duplicate observation
    finally:
        verify.close()
