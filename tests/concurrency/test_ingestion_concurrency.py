"""Real concurrency (threads, independent sessions and connections) over
SQLite: atomic queue claims and observation uniqueness (tasks.md
4.1, 4.5). The claim design (`UPDATE ... WHERE status = 'PENDING'`) is
also correct on PostgreSQL (per-transaction row lock); here it is
exercised on SQLite, the project's dialect for reproducible tests.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from decimal import Decimal

from market_relay.domain.catalog import AssetClass, CatalogService
from market_relay.domain.ingestion import JobQueue
from market_relay.domain.observations import ObservationInput, ObservationStore
from market_relay.domain.observations.models import Job, JobStatus, Observation, ObservationType

NOW = datetime(2026, 1, 5, 8, 0, tzinfo=UTC)


def test_concurrent_workers_never_claim_the_same_job_twice(session_factory) -> None:
    setup = session_factory()
    try:
        queue = JobQueue(setup)
        for i in range(8):
            queue.enqueue_idempotent(
                job_type="fetch_range",
                source="fake",
                dedupe_key=f"job-{i}",
                run_at=NOW,
            )
        setup.commit()
    finally:
        setup.close()

    def claim_one(worker_id: str) -> list[str]:
        session = session_factory()
        try:
            queue = JobQueue(session)
            claimed = queue.claim_next(worker_id=worker_id, now=NOW, limit=8)
            return [str(job.id) for job in claimed]
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(claim_one, [f"worker-{i}" for i in range(8)]))

    all_claimed_ids = [job_id for worker_result in results for job_id in worker_result]
    assert len(all_claimed_ids) == 8
    assert len(set(all_claimed_ids)) == 8  # no row claimed twice

    verify = session_factory()
    try:
        statuses = {job.status for job in verify.query(Job).all()}
        assert statuses == {JobStatus.CLAIMED}
    finally:
        verify.close()


def test_concurrent_identical_observation_writes_produce_a_single_row(session_factory) -> None:
    setup = session_factory()
    try:
        catalog = CatalogService(setup)
        instrument = catalog.register_instrument(
            asset_class=AssetClass.EQUITY, name="SAP SE", isin="DE0007164600"
        )
        listing = catalog.add_listing(
            instrument=instrument, venue="XETR", mic="XETR", ticker="SAP", currency="EUR"
        )
        setup.commit()
        listing_id = listing.id
    finally:
        setup.close()

    def record_once(_: int) -> bool:
        session = session_factory()
        try:
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
                    retrieved_at=NOW,
                )
            )
            session.commit()
            return outcome.created
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=8) as executor:
        created_flags = list(executor.map(record_once, range(8)))

    assert sum(created_flags) == 1  # exactly one winner creates the row

    verify = session_factory()
    try:
        rows = verify.query(Observation).all()
        assert len(rows) == 1
        assert rows[0].revision == 1
    finally:
        verify.close()
