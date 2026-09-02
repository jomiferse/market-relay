"""ORM models for append-only EOD observations and ingestion jobs.

`specs/market-observations/spec.md` requires immutable observations with
full provenance, a raw `close` never substituted by `adjusted_close`, and
deterministic selection without mixing sources. `specs/operations/spec.md`
and `specs/market-data-ingestion/spec.md` require a persistent queue with
retries, cursors, and failure isolation. The full implementation of the job
engine corresponds to section 4 of `tasks.md`; here only the reversible
schema that section will use is fixed.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import Enum, ForeignKey, Numeric, String, UniqueConstraint, event
from sqlalchemy.orm import Mapped, mapped_column, relationship

from market_relay.db.base import Base, UUIDPrimaryKeyMixin, utcnow

if TYPE_CHECKING:
    from market_relay.domain.catalog.models import Listing


class ObservationImmutableError(Exception):
    """An attempt was made to mutate or delete an already-persisted
    `Observation` row.

    Defense in depth at the ORM level: the real append-only guarantee lives
    in the database (`BEFORE UPDATE`/`BEFORE DELETE` triggers from migration
    `0003`, also effective against raw SQL outside the ORM), but failing
    here, before emitting the statement, gives a clearer error for any code
    that uses the SQLAlchemy session directly (e.g. `session.delete(obs)` or
    mutating an attribute and calling `flush()`).
    """


class ObservationType(StrEnum):
    """Nature of the observed value."""

    EOD_CLOSE = "EOD_CLOSE"
    NAV = "NAV"


class QualityStatus(StrEnum):
    """Quality status assigned during ingestion validation."""

    OK = "OK"
    SUSPECT = "SUSPECT"


class Observation(UUIDPrimaryKeyMixin, Base):
    """Immutable EOD observation. No `updated_at` is defined: any
    correction is kept as a new row with an incremented `revision`, never
    as an overwrite of the existing row (tasks.md 4.1). The natural
    idempotency key `(source, credential_scope, external_listing_id,
    session_date, observation_type)` can have several rows — one per
    revision — but each `(natural key, revision)` is unique, and the
    *effective* revision for that key is the one with the highest
    `revision` (see `domain.observations.service`).
    """

    __tablename__ = "observations"
    __table_args__ = (
        UniqueConstraint(
            "source",
            "credential_scope",
            "external_listing_id",
            "session_date",
            "observation_type",
            "revision",
            name="uq_observations_idempotency_key",
        ),
    )

    listing_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("listings.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    # Credential scope: allows several accounts per source without
    # unauthorized deduplication (design.md § "Isolated central
    # credentials"). Never contains the secret itself.
    credential_scope: Mapped[str] = mapped_column(String(64), nullable=False)
    external_listing_id: Mapped[str] = mapped_column(String(128), nullable=False)
    session_date: Mapped[date] = mapped_column(nullable=False)
    observation_type: Mapped[ObservationType] = mapped_column(
        Enum(ObservationType, native_enum=False, length=16, validate_strings=True),
        nullable=False,
    )
    # Revision within the natural idempotency key. 1 is the first
    # insertion; a higher revision represents an explicit correction,
    # never an overwrite of the previous row (tasks.md 4.1).
    revision: Mapped[int] = mapped_column(default=1, nullable=False)

    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    close: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    open: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    high: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    low: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    # `adjusted_close` is kept separately and never substitutes `close`
    # in valuation selection (specs/market-observations/spec.md).
    adjusted_close: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))

    quality_status: Mapped[QualityStatus] = mapped_column(
        Enum(QualityStatus, native_enum=False, length=16, validate_strings=True), nullable=False
    )
    retrieved_at: Mapped[datetime] = mapped_column(nullable=False)
    # These immutable references explain why acquisition and persistence were
    # authorized at retrieval time. Presentation and redistribution remain
    # dynamic policy checks and are deliberately not snapshotted here.
    retrieval_policy_decision_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("source_policy_decisions.id", ondelete="RESTRICT"), nullable=True
    )
    storage_policy_decision_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("source_policy_decisions.id", ondelete="RESTRICT"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(default=utcnow, nullable=False)

    listing: Mapped[Listing] = relationship()
    # There is no `is_publishable` column: if a source loses its
    # publication authorization, no row changes. Publishability is derived
    # on each query from the *current* state of `SourcePolicyDecision`
    # (`PolicyGate.is_publication_authorized`, see `domain.observations.selection`),
    # so that a revocation never requires an `UPDATE` over the append-only
    # history (specs/market-observations/spec.md § "Preserved history").


@event.listens_for(Observation, "before_update")
def _reject_observation_update(mapper: object, connection: object, target: Observation) -> None:
    raise ObservationImmutableError(
        f"Observation {target.id} is append-only: UPDATE not allowed. A "
        "correction SHALL be recorded as a new row with an incremented "
        "`revision` (tasks.md 4.1)."
    )


@event.listens_for(Observation, "before_delete")
def _reject_observation_delete(mapper: object, connection: object, target: Observation) -> None:
    raise ObservationImmutableError(
        f"Observation {target.id} is append-only: DELETE not allowed. The "
        "history is preserved intact for auditing "
        "(specs/market-observations/spec.md § 'Preserved history')."
    )


class JobStatus(StrEnum):
    """Status of an ingestion job's lifecycle."""

    PENDING = "PENDING"
    CLAIMED = "CLAIMED"
    RUNNING = "RUNNING"
    WAITING_FOR_PUBLICATION = "WAITING_FOR_PUBLICATION"
    DONE = "DONE"
    FAILED = "FAILED"


class Job(UUIDPrimaryKeyMixin, Base):
    """Unit of work of the persistent queue (specs/operations/spec.md)."""

    __tablename__ = "jobs"
    __table_args__ = (
        # Deduplication key for idempotent enqueueing (tasks.md 4.5): a
        # scheduler that runs again over the same range/listing SHALL not
        # create a duplicate job.
        UniqueConstraint("dedupe_key", name="uq_jobs_dedupe_key"),
    )

    job_type: Mapped[str] = mapped_column(String(64), nullable=False)
    # Stably identifies the logical job (source + listing + observation
    # type + session range) so that re-enqueueing the same job is a no-op
    # instead of a duplicate row.
    dedupe_key: Mapped[str] = mapped_column(String(256), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    listing_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("listings.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, native_enum=False, length=24, validate_strings=True),
        nullable=False,
        index=True,
    )
    # Serialized progress cursor (e.g. pending range).
    cursor: Mapped[str | None] = mapped_column(String(512))
    attempt_count: Mapped[int] = mapped_column(default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(default=5, nullable=False)
    next_run_at: Mapped[datetime] = mapped_column(nullable=False)
    claimed_by: Mapped[str | None] = mapped_column(String(128))
    claimed_at: Mapped[datetime | None] = mapped_column()
    # Claim generation: incremented on rescheduling, invalidating stale
    # claims (design.md § "Single scheduler with persistent queue").
    generation: Mapped[int] = mapped_column(default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(String(1024))
    created_at: Mapped[datetime] = mapped_column(default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow, nullable=False)


class SchedulerRunStatus(StrEnum):
    """Outcome of one bounded phase of a single scheduled entry point
    execution (tasks.md 6.1).
    """

    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"


class SchedulerRun(UUIDPrimaryKeyMixin, Base):
    """One durable record per execution of the single scheduled entry point
    (tasks.md 6.1; specs/operations/spec.md § "Minimum observability":
    "successful executions of the scheduler and worker").

    `scheduler_status` reflects the refresh-and-dispatch phase
    (`domain.ingestion.scheduler_service.refresh_and_dispatch`) and
    `worker_status` the bounded job-processing phase
    (`claim_and_process`); both start `NULL` and are filled in as each
    phase completes. Committed through its own connection, independent of
    the cycle's own work session
    (`domain.ingestion.scheduler_runs.SchedulerRunRecorder`), so that a
    crash partway through one phase never erases the already-recorded
    outcome of the other — this row is the durable signal the "successful
    scheduler/worker execution" metrics are built from, and it survives
    even when the cycle's own transaction rolls back.
    """

    __tablename__ = "scheduler_runs"

    started_at: Mapped[datetime] = mapped_column(default=utcnow, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column()
    scheduler_status: Mapped[SchedulerRunStatus | None] = mapped_column(
        Enum(SchedulerRunStatus, native_enum=False, length=16, validate_strings=True)
    )
    worker_status: Mapped[SchedulerRunStatus | None] = mapped_column(
        Enum(SchedulerRunStatus, native_enum=False, length=16, validate_strings=True)
    )
    # Bounded generic code (`domain.ingestion.error_codes`), never a
    # provider's raw exception text, populated only when a phase failed.
    error_code: Mapped[str | None] = mapped_column(String(64))
