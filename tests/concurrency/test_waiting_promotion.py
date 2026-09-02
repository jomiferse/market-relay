"""Deterministic, concurrent-safe publication-wait promotion."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from typing import cast
from uuid import UUID

from market_relay.adapters.fake.provider import FakeMarketDataProvider
from market_relay.domain.catalog.models import AssetClass
from market_relay.domain.ingestion.dispatch import plan_and_enqueue
from market_relay.domain.ingestion.planning import RecoveryLimits
from market_relay.domain.ingestion.queue import JobQueue
from market_relay.domain.observations.models import Job, JobStatus, ObservationType

NOW = datetime(2026, 1, 9, 18, 0, tzinfo=UTC)  # Friday: fake fund NAV waits


def _dispatch_waiting(queue: JobQueue) -> Job:
    result = plan_and_enqueue(
        queue=queue,
        calendar=FakeMarketDataProvider(),
        limits=RecoveryLimits(max_lookback_days=1, max_sessions_per_chunk=2),
        listing_id=cast("UUID", None),
        asset_class=AssetClass.FUND,
        venue="FUND",
        mic=None,
        source="fake",
        credential_scope="default",
        external_listing_id="FAKE-FUND",
        observation_type=ObservationType.NAV,
        last_completed_session=date(2026, 1, 8),
        today=NOW.date(),
        now=NOW,
        waiting_retry_seconds=60,
    )
    assert result.waiting_job is not None
    return result.waiting_job.job


def test_waiting_is_not_claimable_before_due_and_is_claimable_at_or_after_due(db_session) -> None:
    queue = JobQueue(db_session)
    waiting = _dispatch_waiting(queue)
    assert waiting.status == JobStatus.WAITING_FOR_PUBLICATION
    assert queue.claim_next(worker_id="early", now=NOW + timedelta(seconds=59)) == []
    exact = queue.claim_next(worker_id="exact", now=NOW + timedelta(seconds=60))
    assert len(exact) == 1

    second = (
        JobQueue(db_session)
        .enqueue_idempotent(job_type="fetch_range", source="fake", dedupe_key="overdue", run_at=NOW)
        .job
    )
    second.status = JobStatus.WAITING_FOR_PUBLICATION
    db_session.commit()
    overdue = queue.claim_next(worker_id="late", now=NOW + timedelta(minutes=2))
    assert len(overdue) == 1


def test_redispatch_keeps_one_waiting_job(db_session) -> None:
    queue = JobQueue(db_session)
    first = _dispatch_waiting(queue)
    second = _dispatch_waiting(queue)
    assert first.id == second.id
    assert db_session.query(Job).count() == 1


def test_concurrent_due_promotion_produces_one_claim(session_factory) -> None:
    setup = session_factory()
    try:
        _dispatch_waiting(JobQueue(setup))
        setup.commit()
    finally:
        setup.close()

    def promote_and_claim(worker: str) -> list[str]:
        session = session_factory()
        try:
            jobs = JobQueue(session).claim_next(
                worker_id=worker, now=NOW + timedelta(seconds=60), limit=1
            )
            return [str(job.id) for job in jobs]
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(promote_and_claim, [f"worker-{index}" for index in range(4)]))
    claimed = [job_id for result in results for job_id in result]
    assert len(claimed) == 1
