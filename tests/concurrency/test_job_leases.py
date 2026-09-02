"""Lease recovery and fencing for crashed ingestion workers."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest

from market_relay.domain.ingestion.queue import JobQueue, StaleJobClaimError
from market_relay.domain.observations.models import Job, JobStatus

NOW = datetime(2026, 1, 5, 8, 0, tzinfo=UTC)


def _enqueue(queue: JobQueue, *, max_attempts: int = 5) -> Job:
    return queue.enqueue_idempotent(
        job_type="fetch_range",
        source="fake",
        dedupe_key="lease-job",
        run_at=NOW,
        max_attempts=max_attempts,
    ).job


@pytest.mark.parametrize(
    "running", [False, True], ids=["crash-after-claimed", "crash-after-running"]
)
def test_expired_claim_or_running_job_is_recovered(db_session, running: bool) -> None:
    queue = JobQueue(db_session)
    _enqueue(queue)
    original = queue.claim_next(worker_id="crashed", now=NOW, lease_seconds=60)[0]
    old_generation = original.generation
    if running:
        queue.mark_running(original, worker_id="crashed", generation=old_generation)

    assert (
        queue.claim_next(worker_id="early", now=NOW + timedelta(seconds=59), lease_seconds=60) == []
    )
    recovered = queue.claim_next(
        worker_id="replacement", now=NOW + timedelta(seconds=60), lease_seconds=60
    )
    assert len(recovered) == 1
    assert recovered[0].claimed_by == "replacement"
    assert recovered[0].generation > old_generation
    assert recovered[0].attempt_count == 1


def test_stale_worker_cannot_complete_after_recovery(db_session) -> None:
    queue = JobQueue(db_session)
    _enqueue(queue)
    stale = queue.claim_next(worker_id="old", now=NOW, lease_seconds=10)[0]
    stale_generation = stale.generation
    queue.mark_running(stale, worker_id="old", generation=stale_generation)
    current = queue.claim_next(
        worker_id="current", now=NOW + timedelta(seconds=10), lease_seconds=10
    )[0]
    queue.mark_running(current, worker_id="current", generation=current.generation)
    queue.mark_done(
        current,
        worker_id="current",
        generation=current.generation,
        now=NOW + timedelta(seconds=11),
    )

    with pytest.raises(StaleJobClaimError):
        queue.mark_done(
            stale,
            worker_id="old",
            generation=stale_generation,
            now=NOW + timedelta(seconds=12),
        )
    db_session.refresh(current)
    assert current.status == JobStatus.DONE


def test_concurrent_recovery_has_one_owner_and_one_success(session_factory) -> None:
    setup = session_factory()
    try:
        queue = JobQueue(setup)
        _enqueue(queue)
        queue.claim_next(worker_id="crashed", now=NOW, lease_seconds=10)
    finally:
        setup.close()

    def recover(worker: str) -> list[Job]:
        session = session_factory()
        try:
            return JobQueue(session).claim_next(
                worker_id=worker,
                now=NOW + timedelta(seconds=10),
                lease_seconds=10,
            )
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(recover, [f"worker-{index}" for index in range(4)]))
    claims = [job for result in results for job in result]
    assert len(claims) == 1

    session = session_factory()
    try:
        stored = session.get(Job, claims[0].id)
        assert stored is not None
        assert stored.status == JobStatus.CLAIMED
        assert stored.attempt_count == 1
    finally:
        session.close()


def test_recovered_attempt_can_retry_and_complete_only_once(db_session) -> None:
    queue = JobQueue(db_session)
    _enqueue(queue)
    queue.claim_next(worker_id="crashed", now=NOW, lease_seconds=10)
    recovered = queue.claim_next(
        worker_id="replacement", now=NOW + timedelta(seconds=10), lease_seconds=10
    )[0]
    generation = recovered.generation
    queue.mark_running(recovered, worker_id="replacement", generation=generation)
    queue.mark_failed(
        recovered,
        worker_id="replacement",
        generation=generation,
        error="bounded_failure",
        now=NOW + timedelta(seconds=11),
    )
    retry_at = recovered.next_run_at.replace(tzinfo=UTC)
    retry = queue.claim_next(worker_id="retry", now=retry_at, lease_seconds=10)[0]
    queue.mark_running(retry, worker_id="retry", generation=retry.generation)
    queue.mark_done(retry, worker_id="retry", generation=retry.generation, now=retry_at)
    with pytest.raises(StaleJobClaimError):
        queue.mark_done(retry, worker_id="retry", generation=retry.generation, now=retry_at)
    assert retry.status == JobStatus.DONE
