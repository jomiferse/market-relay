"""Persistent queue: idempotent enqueueing, claims, backoff and quota (tasks.md 4.5)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from market_relay.domain.ingestion import EnqueueResult, JobQueue, backoff_seconds
from market_relay.domain.ingestion.queue import StaleJobClaimError
from market_relay.domain.observations.models import Job, JobStatus

NOW = datetime(2026, 1, 5, 8, 0, tzinfo=UTC)


def _status(job: Job) -> JobStatus:
    """Indirection to prevent mypy from narrowing `job.status` to a literal
    between two calls that mutate it (a known narrowing limitation for
    attributes mutated by a call to another object)."""

    return job.status


def _enqueue(
    queue: JobQueue,
    *,
    dedupe_key: str = "job-1",
    run_at: datetime = NOW,
    max_attempts: int = 3,
) -> EnqueueResult:
    return queue.enqueue_idempotent(
        job_type="fetch_range",
        source="fake",
        dedupe_key=dedupe_key,
        run_at=run_at,
        max_attempts=max_attempts,
    )


def _claim(queue: JobQueue, *, worker_id: str = "worker-a") -> Job:
    claimed = queue.claim_next(worker_id=worker_id, now=NOW)
    assert len(claimed) == 1
    return claimed[0]


def test_enqueue_idempotent_reenqueue_is_a_no_op(db_session) -> None:
    queue = JobQueue(db_session)

    first = _enqueue(queue)
    second = _enqueue(queue)

    assert first.created is True
    assert second.created is False
    assert first.job.id == second.job.id

    from market_relay.domain.observations.models import Job

    assert db_session.query(Job).count() == 1


def test_claim_next_marks_job_claimed_and_is_not_claimed_twice(db_session) -> None:
    queue = JobQueue(db_session)
    _enqueue(queue)

    first_claim = queue.claim_next(worker_id="worker-a", now=NOW)
    second_claim = queue.claim_next(worker_id="worker-b", now=NOW)

    assert len(first_claim) == 1
    assert first_claim[0].status == JobStatus.CLAIMED
    assert first_claim[0].claimed_by == "worker-a"
    assert second_claim == []


def test_claim_respects_next_run_at(db_session) -> None:
    queue = JobQueue(db_session)
    _enqueue(queue, run_at=NOW + timedelta(hours=1))

    claimed = queue.claim_next(worker_id="worker-a", now=NOW)

    assert claimed == []


def test_backoff_grows_and_is_capped() -> None:
    values = [backoff_seconds(n) for n in range(1, 10)]
    assert values == sorted(values)
    assert values[-1] <= 3600
    assert backoff_seconds(0) == 0


def test_mark_failed_retries_with_backoff_until_max_attempts(db_session) -> None:
    queue = JobQueue(db_session)
    _enqueue(queue, max_attempts=2)
    job = _claim(queue)

    queue.mark_failed(job, worker_id="worker-a", generation=job.generation, error="boom", now=NOW)
    assert _status(job) == JobStatus.PENDING
    assert job.attempt_count == 1
    assert job.next_run_at.replace(tzinfo=UTC) > NOW

    job = queue.claim_next(worker_id="worker-a", now=job.next_run_at)[0]
    queue.mark_failed(
        job, worker_id="worker-a", generation=job.generation, error="boom again", now=NOW
    )
    assert _status(job) == JobStatus.FAILED
    assert job.attempt_count == 2


def test_mark_failed_sanitizes_error_message(db_session) -> None:
    queue = JobQueue(db_session)
    _enqueue(queue, max_attempts=5)
    job = _claim(queue)

    queue.mark_failed(
        job,
        worker_id="worker-a",
        generation=job.generation,
        error="auth failed for https://user:s3cr3t@example.test/api",
        now=NOW,
    )

    assert "s3cr3t" not in (job.last_error or "")
    assert "***" in (job.last_error or "")


def test_defer_for_quota_does_not_count_as_failed_attempt(db_session) -> None:
    """specs/market-data-ingestion/spec.md § 'Quota exhausted': the job is
    deferred without counting a failure.
    """

    queue = JobQueue(db_session)
    _enqueue(queue, max_attempts=2)
    job = _claim(queue)
    reset_at = NOW + timedelta(hours=2)

    queue.defer_for_quota(
        job,
        worker_id="worker-a",
        generation=job.generation,
        reset_at=reset_at,
        now=NOW,
    )

    assert job.status == JobStatus.PENDING
    assert job.attempt_count == 0
    assert job.next_run_at.replace(tzinfo=UTC) == reset_at

    claimed_before_reset = queue.claim_next(worker_id="worker-a", now=NOW)
    assert claimed_before_reset == []


def test_waiting_for_publication_does_not_increment_attempt_count(db_session) -> None:
    queue = JobQueue(db_session)
    _enqueue(queue, max_attempts=2)
    job = _claim(queue)

    queue.mark_waiting_for_publication(
        job,
        worker_id="worker-a",
        generation=job.generation,
        retry_at=NOW + timedelta(hours=6),
    )

    assert job.status == JobStatus.WAITING_FOR_PUBLICATION
    assert job.attempt_count == 0


def test_mark_done_is_reentrant_after_confirmation_lost(db_session) -> None:
    """Re-running an already completed job must not produce an
    inconsistent state (specs/market-data-ingestion/spec.md § 'Retry after
    lost confirmation').
    """

    queue = JobQueue(db_session)
    _enqueue(queue)
    job = _claim(queue)
    generation = job.generation

    queue.mark_running(job, worker_id="worker-a", generation=generation)
    queue.mark_done(job, worker_id="worker-a", generation=generation, now=NOW)
    with pytest.raises(StaleJobClaimError):
        queue.mark_done(
            job,
            worker_id="worker-a",
            generation=generation,
            now=NOW + timedelta(seconds=1),
        )

    assert job.status == JobStatus.DONE


def test_depth_and_oldest_pending_age_are_observable(db_session) -> None:
    # `Job.created_at` uses the process's real clock (`utcnow`), not `NOW`
    # (the tests' fictitious date): it is compared against the real clock.
    queue = JobQueue(db_session)
    _enqueue(queue, dedupe_key="job-a", run_at=NOW)
    _enqueue(queue, dedupe_key="job-b", run_at=NOW)

    assert queue.depth() == 2
    check_at = datetime.now(UTC) + timedelta(minutes=10)
    age = queue.oldest_pending_age_seconds(now=check_at)
    assert age is not None
    assert age >= 600
