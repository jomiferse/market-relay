"""Sanitized operational metrics (tasks.md 6.2; specs/operations/spec.md
§ "Minimum observability").
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from market_relay.db.base import utcnow
from market_relay.domain.ingestion.metrics import collect_scheduler_metrics
from market_relay.domain.ingestion.queue import JobQueue
from market_relay.domain.observations.models import Job, JobStatus

NOW = datetime(2026, 1, 9, 10, 0, tzinfo=UTC)


def test_metrics_report_depth_age_successes_failures_and_quota(db_session: Session) -> None:
    queue = JobQueue(db_session)

    queue.enqueue_idempotent(job_type="fetch_range", source="fake", dedupe_key="done-1", run_at=NOW)
    done_job = queue.claim_next(worker_id="metrics", now=NOW, limit=1)[0]
    queue.mark_running(done_job, worker_id="metrics", generation=done_job.generation)
    queue.mark_done(done_job, worker_id="metrics", generation=done_job.generation, now=NOW)
    queue.enqueue_idempotent(
        job_type="fetch_range", source="fake", dedupe_key="failed-1", run_at=NOW, max_attempts=1
    )
    failed_job = queue.claim_next(worker_id="metrics", now=NOW, limit=1)[0]
    queue.mark_failed(
        failed_job,
        worker_id="metrics",
        generation=failed_job.generation,
        error="boom",
        now=NOW,
    )
    queue.enqueue_idempotent(
        job_type="fetch_range", source="fake", dedupe_key="pending-1", run_at=NOW
    )
    db_session.commit()

    snapshot = collect_scheduler_metrics(
        session=db_session,
        now=utcnow(),
        stalled_threshold_seconds=3600,
        sources=("fake",),
    )

    assert snapshot.pending_jobs == 1
    assert snapshot.pending_jobs_by_source == {"fake": 1}
    assert snapshot.done_jobs == 1
    assert snapshot.failed_jobs_by_source == {"fake": 1}
    assert len(snapshot.quota_by_source) == 1
    assert snapshot.quota_by_source[0].source == "fake"
    assert snapshot.quota_by_source[0].error is None
    assert snapshot.quota_by_source[0].exhausted is False


def test_metrics_flag_a_source_as_stalled_only_past_the_threshold(db_session: Session) -> None:
    db_session.add(
        Job(
            job_type="fetch_range",
            dedupe_key="stalled-1",
            source="fake",
            status=JobStatus.PENDING,
            created_at=utcnow() - timedelta(hours=2),
            next_run_at=utcnow(),
        )
    )
    db_session.commit()

    snapshot = collect_scheduler_metrics(
        session=db_session, now=utcnow(), stalled_threshold_seconds=3600, sources=("fake",)
    )

    assert snapshot.stalled_sources == ("fake",)
    assert snapshot.oldest_pending_seconds is not None
    assert snapshot.oldest_pending_seconds >= 7000


def test_metrics_never_include_the_sanitized_error_of_a_different_source(
    db_session: Session,
) -> None:
    """A source with no registered adapter is isolated: its `error`
    (already sanitized) never prevents computing the healthy source's
    metrics, nor contaminates its own entry (specs/operations/spec.md
    § "Safe degraded operation").
    """

    snapshot = collect_scheduler_metrics(
        session=db_session,
        now=utcnow(),
        stalled_threshold_seconds=3600,
        sources=("fake", "unregistered-source"),
    )

    by_source = {quota.source: quota for quota in snapshot.quota_by_source}
    assert by_source["fake"].error is None
    assert by_source["unregistered-source"].remaining is None
    # `error` is always one of the bounded, generic codes from
    # `domain.ingestion.error_codes` — never the exception's own text, even
    # sanitized: a provider's free text could carry a secret in a shape the
    # redaction patterns do not cover (tasks.md 6.2).
    assert by_source["unregistered-source"].error == "unknown_source"
