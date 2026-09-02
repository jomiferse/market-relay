"""Persistent job queue: idempotent enqueueing and atomic claims.

`specs/market-data-ingestion/spec.md` § "Idempotence and concurrency"
requires ingestion to be retry-safe and avoid duplicates even with
concurrent workers. `design.md` § "Single scheduler with persistent queue"
requires atomic locks or claims and unique constraints to control
concurrency, valid both in PostgreSQL (deployment engine) and SQLite
(reproducible tests).

The claim is implemented as a single conditioned `UPDATE ... WHERE id = :id
AND status = 'PENDING'` statement: it is atomic in both dialects because any
given row can only have one transaction modifying it at a time (row lock in
PostgreSQL, whole-database write lock in SQLite), and the resulting
`rowcount` unambiguously indicates whether the worker won the race.
`SELECT ... FOR UPDATE SKIP LOCKED` is not used, to keep a single correct
code path across the two supported dialects; the cost is contention under
high concurrency, acceptable for MVP volume.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TypeVar, cast

from sqlalchemy import CursorResult, case, func, select, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from market_relay.domain.governance.credentials import sanitize_message
from market_relay.domain.observations.models import Job, JobStatus

# Bounded exponential backoff (specs/market-data-ingestion/spec.md § "Quotas
# and partial failures"): grows with the number of attempts up to a fixed
# cap, never retries immediately nor indefinitely fast.
_BACKOFF_BASE_SECONDS = 30
_BACKOFF_CAP_SECONDS = 3600
_DEFAULT_QUOTA_DEFER_SECONDS = 3600
_LOCK_RETRY_ATTEMPTS = 10
_LOCK_RETRY_SLEEP_SECONDS = 0.05

_T = TypeVar("_T")


def backoff_seconds(attempt_count: int) -> int:
    """Bounded exponential backoff: `base * 2**(attempt-1)`, capped at `cap`."""

    if attempt_count <= 0:
        return 0
    return int(min(_BACKOFF_BASE_SECONDS * (2 ** (attempt_count - 1)), _BACKOFF_CAP_SECONDS))


@dataclass(frozen=True, slots=True)
class EnqueueResult:
    job: Job
    created: bool


class StaleJobClaimError(Exception):
    """The caller no longer owns the generation of a claimed job."""


class JobQueue:
    """Use cases of the persistent queue over a SQLAlchemy session."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def enqueue_idempotent(
        self,
        *,
        job_type: str,
        source: str,
        dedupe_key: str,
        listing_id: uuid.UUID | None = None,
        cursor: str | None = None,
        run_at: datetime,
        max_attempts: int = 5,
    ) -> EnqueueResult:
        """Enqueues a job or returns the existing one for `dedupe_key`.

        Re-enqueueing the same logical job (same source, listing, and range)
        SHALL be a no-op, never a duplicate row
        (specs/market-data-ingestion/spec.md § "Retry after lost
        confirmation").
        """

        job = Job(
            job_type=job_type,
            source=source,
            dedupe_key=dedupe_key,
            listing_id=listing_id,
            status=JobStatus.PENDING,
            cursor=cursor,
            next_run_at=run_at,
            max_attempts=max_attempts,
        )
        try:
            with self._session.begin_nested():
                self._session.add(job)
                self._session.flush()
        except IntegrityError:
            existing = self._session.scalars(
                select(Job).where(Job.dedupe_key == dedupe_key)
            ).first()
            if existing is None:  # pragma: no cover - defensive, should not happen
                raise
            return EnqueueResult(job=existing, created=False)
        return EnqueueResult(job=job, created=True)

    def claim_next(
        self,
        *,
        worker_id: str,
        now: datetime,
        source: str | None = None,
        limit: int = 1,
        lease_seconds: int = 300,
    ) -> list[Job]:
        """Atomically claims up to `limit` eligible `PENDING` jobs.

        Under concurrent workers, each row is won by at most a single
        worker: the `UPDATE` conditioned on `status == PENDING` ensures that
        at most one transaction sees `rowcount == 1` for a given row.
        """

        self.recover_expired(now=now, lease_seconds=lease_seconds)
        self.promote_due_waiting(now=now)

        candidates_stmt = select(Job.id).where(
            Job.status == JobStatus.PENDING, Job.next_run_at <= now
        )
        if source is not None:
            candidates_stmt = candidates_stmt.where(Job.source == source)
        candidates_stmt = candidates_stmt.order_by(Job.next_run_at, Job.id).limit(limit * 5)

        candidate_ids: Sequence[uuid.UUID] = self._retry_on_lock(
            lambda: self._session.scalars(candidates_stmt).all()
        )

        claimed: list[Job] = []
        for job_id in candidate_ids:
            if len(claimed) >= limit:
                break
            claimed_job = self._try_claim_one(job_id=job_id, worker_id=worker_id, now=now)
            if claimed_job is not None:
                claimed.append(claimed_job)
        return claimed

    def promote_due_waiting(self, *, now: datetime) -> int:
        """Atomically makes publication-waiting jobs claimable when due."""

        result = cast(
            "CursorResult[Job]",
            self._session.execute(
                update(Job)
                .where(
                    Job.status == JobStatus.WAITING_FOR_PUBLICATION,
                    Job.next_run_at <= now,
                )
                .values(status=JobStatus.PENDING, updated_at=now)
                .execution_options(synchronize_session=False)
            ),
        )
        self._session.commit()
        return result.rowcount

    def recover_expired(self, *, now: datetime, lease_seconds: int) -> int:
        """Atomically recover abandoned claims and invalidate former owners."""

        cutoff = now - timedelta(seconds=lease_seconds)
        exhausted = Job.attempt_count + 1 >= Job.max_attempts
        result = cast(
            "CursorResult[Job]",
            self._session.execute(
                update(Job)
                .where(
                    Job.status.in_((JobStatus.CLAIMED, JobStatus.RUNNING)),
                    Job.claimed_at <= cutoff,
                )
                .values(
                    status=case((exhausted, JobStatus.FAILED), else_=JobStatus.PENDING),
                    attempt_count=Job.attempt_count + 1,
                    next_run_at=now,
                    claimed_by=None,
                    claimed_at=None,
                    generation=Job.generation + 1,
                    last_error="claim_lease_expired",
                    updated_at=now,
                )
                .execution_options(synchronize_session=False)
            ),
        )
        self._session.commit()
        return result.rowcount

    def _try_claim_one(self, *, job_id: uuid.UUID, worker_id: str, now: datetime) -> Job | None:
        def attempt() -> Job | None:
            result = cast(
                "CursorResult[Job]",
                self._session.execute(
                    update(Job)
                    .where(Job.id == job_id, Job.status == JobStatus.PENDING)
                    .values(
                        status=JobStatus.CLAIMED,
                        claimed_by=worker_id,
                        claimed_at=now,
                        generation=Job.generation + 1,
                    )
                    .execution_options(synchronize_session=False)
                ),
            )
            self._session.commit()
            if result.rowcount != 1:
                return None
            return self._session.get(Job, job_id, populate_existing=True)

        return self._retry_on_lock(attempt)

    def claim_job(self, job: Job, *, worker_id: str, now: datetime) -> Job:
        """Claim a specific pending job, primarily for direct runner use."""

        claimed = self._try_claim_one(job_id=job.id, worker_id=worker_id, now=now)
        if claimed is None:
            raise StaleJobClaimError(f"Job {job.id} is not available to {worker_id}.")
        return claimed

    @staticmethod
    def _retry_on_lock(action: Callable[[], _T]) -> _T:
        """Retries on a locking `OperationalError` (e.g. "database is
        locked" in SQLite under real concurrent writes from different
        threads). In PostgreSQL the row lock waits instead of failing, so
        this retry is normally not exercised on that dialect.
        """

        last_exc: OperationalError | None = None
        for _ in range(_LOCK_RETRY_ATTEMPTS):
            try:
                return action()
            except OperationalError as exc:
                last_exc = exc
                time.sleep(_LOCK_RETRY_SLEEP_SECONDS)
        assert last_exc is not None
        raise last_exc

    def _owned_transition(
        self,
        job: Job,
        *,
        worker_id: str,
        generation: int,
        allowed_statuses: tuple[JobStatus, ...],
        values: dict[str, object],
    ) -> None:
        result = cast(
            "CursorResult[Job]",
            self._session.execute(
                update(Job)
                .where(
                    Job.id == job.id,
                    Job.status.in_(allowed_statuses),
                    Job.claimed_by == worker_id,
                    Job.generation == generation,
                )
                .values(**values)
                .execution_options(synchronize_session=False)
            ),
        )
        if result.rowcount != 1:
            self._session.expire_all()
            raise StaleJobClaimError(
                f"Job {job.id} generation {generation} is no longer owned by {worker_id}."
            )
        self._session.expire(job)

    def assert_owned(self, job: Job, *, worker_id: str, generation: int) -> None:
        """Fence storage performed after a provider call."""

        owned = self._session.scalar(
            select(Job.id).where(
                Job.id == job.id,
                Job.status.in_((JobStatus.CLAIMED, JobStatus.RUNNING)),
                Job.claimed_by == worker_id,
                Job.generation == generation,
            )
        )
        if owned is None:
            raise StaleJobClaimError(
                f"Job {job.id} generation {generation} is no longer owned by {worker_id}."
            )

    def mark_running(self, job: Job, *, worker_id: str, generation: int) -> None:
        self._owned_transition(
            job,
            worker_id=worker_id,
            generation=generation,
            allowed_statuses=(JobStatus.CLAIMED,),
            values={"status": JobStatus.RUNNING},
        )

    def mark_done(self, job: Job, *, worker_id: str, generation: int, now: datetime) -> None:
        self._owned_transition(
            job,
            worker_id=worker_id,
            generation=generation,
            allowed_statuses=(JobStatus.RUNNING,),
            values={"status": JobStatus.DONE, "last_error": None, "updated_at": now},
        )

    def mark_waiting_for_publication(
        self,
        job: Job,
        *,
        worker_id: str,
        generation: int,
        retry_at: datetime,
    ) -> None:
        """`WAITING_FOR_PUBLICATION` does not count as an error: it does not
        increment `attempt_count` (specs/market-data-ingestion/spec.md §
        "NAV not yet published").
        """

        self._owned_transition(
            job,
            worker_id=worker_id,
            generation=generation,
            allowed_statuses=(JobStatus.CLAIMED, JobStatus.RUNNING),
            values={
                "status": JobStatus.WAITING_FOR_PUBLICATION,
                "next_run_at": retry_at,
                "last_error": None,
                "claimed_by": None,
                "claimed_at": None,
            },
        )

    def defer_for_quota(
        self,
        job: Job,
        *,
        worker_id: str,
        generation: int,
        reset_at: datetime | None,
        now: datetime,
    ) -> None:
        """Quota exhausted: defers the job without counting a failure and
        without having made any further useless request to the provider
        (specs/market-data-ingestion/spec.md § "Quota exhausted").
        """

        self._owned_transition(
            job,
            worker_id=worker_id,
            generation=generation,
            allowed_statuses=(JobStatus.CLAIMED, JobStatus.RUNNING),
            values={
                "status": JobStatus.PENDING,
                "next_run_at": reset_at or (now + timedelta(seconds=_DEFAULT_QUOTA_DEFER_SECONDS)),
                "last_error": None,
                "claimed_by": None,
                "claimed_at": None,
            },
        )

    def mark_failed(
        self,
        job: Job,
        *,
        worker_id: str,
        generation: int,
        error: str,
        now: datetime,
    ) -> None:
        """Records a sanitized failure and retries with bounded backoff up
        to `max_attempts`; beyond that the job stays `FAILED` (terminal) and
        does not block other jobs or instruments
        (specs/market-data-ingestion/spec.md § "Quotas and partial
        failures").
        """

        next_attempt = job.attempt_count + 1
        next_status = JobStatus.FAILED if next_attempt >= job.max_attempts else JobStatus.PENDING
        self._owned_transition(
            job,
            worker_id=worker_id,
            generation=generation,
            allowed_statuses=(JobStatus.CLAIMED, JobStatus.RUNNING),
            values={
                "attempt_count": next_attempt,
                "last_error": sanitize_message(error)[:1024],
                "status": next_status,
                "next_run_at": now + timedelta(seconds=backoff_seconds(next_attempt)),
                "claimed_by": None,
                "claimed_at": None,
                "updated_at": now,
            },
        )

    def depth(self, *, source: str | None = None) -> int:
        stmt = select(Job).where(Job.status.in_((JobStatus.PENDING, JobStatus.CLAIMED)))
        if source is not None:
            stmt = stmt.where(Job.source == source)
        return len(list(self._session.scalars(stmt).all()))

    def oldest_pending_age_seconds(self, *, now: datetime) -> float | None:
        stmt = (
            select(Job.created_at)
            .where(Job.status == JobStatus.PENDING)
            .order_by(Job.created_at)
            .limit(1)
        )
        oldest = self._session.scalar(stmt)
        if oldest is None:
            return None
        if oldest.tzinfo is None:
            # SQLite does not preserve tzinfo on the round trip; domain
            # timestamps are always generated in UTC (`utcnow`).
            oldest = oldest.replace(tzinfo=UTC)
        return (now - oldest).total_seconds()

    def pending_by_source(self) -> dict[str, int]:
        """Queue depth (`PENDING`+`CLAIMED`) grouped by source, for the
        sanitized operational metrics (tasks.md 6.2). `source` is an
        internal identifier of a registered adapter (e.g. "fake"), never a
        credential.
        """

        stmt = (
            select(Job.source, func.count(Job.id))
            .where(Job.status.in_((JobStatus.PENDING, JobStatus.CLAIMED)))
            .group_by(Job.source)
        )
        return {source: count for source, count in self._session.execute(stmt).all()}

    def oldest_pending_age_by_source(self, *, now: datetime) -> dict[str, float]:
        """Age in seconds of the oldest `PENDING` job, per source (tasks.md
        6.2 § "Stalled jobs": lets an operator identify which specific
        source is lagging, without revealing any credential).
        """

        stmt = (
            select(Job.source, func.min(Job.created_at))
            .where(Job.status == JobStatus.PENDING)
            .group_by(Job.source)
        )
        ages: dict[str, float] = {}
        for source, oldest in self._session.execute(stmt).all():
            if oldest.tzinfo is None:
                oldest = oldest.replace(tzinfo=UTC)
            ages[source] = (now - oldest).total_seconds()
        return ages

    def done_count(self) -> int:
        """Total count of completed (`DONE`) jobs: the sanitized signal of
        "successful worker executions" (specs/operations/spec.md §
        "Minimum observability").
        """

        stmt = select(func.count(Job.id)).where(Job.status == JobStatus.DONE)
        return self._session.scalar(stmt) or 0

    def failed_by_source(self) -> dict[str, int]:
        """Count of `FAILED` (terminal) jobs, grouped by source."""

        stmt = (
            select(Job.source, func.count(Job.id))
            .where(Job.status == JobStatus.FAILED)
            .group_by(Job.source)
        )
        return {source: count for source, count in self._session.execute(stmt).all()}
