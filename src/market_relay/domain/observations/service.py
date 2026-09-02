"""Append-only observation storage with exact idempotency.

`specs/market-observations/spec.md` requires preserving full provenance and
never silently overwriting. `tasks.md` 4.1 requires exact uniqueness by
`(source, credentialScope, externalListingId, sessionDate, observationType)`
and idempotency under concurrent inserts, with corrections represented as
new revisions — never as an `UPDATE` over the previous row.

Algorithm: each insertion attempt computes the next free revision for the
natural key and inserts it within a `SAVEPOINT`. If two processes compete
for the same revision, the unique constraint on `(natural key, revision)`
rejects the loser with `IntegrityError`; that process rolls back only the
`SAVEPOINT`, rereads the state, and decides: if the already-persisted value
is identical to what it was trying to write, the operation is a duplicate
retry (idempotent, creates no row); if it differs, it is a legitimate
correction that competed for the same revision number and must retry with
the next one.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from market_relay.domain.observations.models import Observation, ObservationType, QualityStatus


class RevisionRaceExhaustedError(Exception):
    """Retries were exhausted due to contention on the revision key.

    Should not happen in normal operation (it implies a storm of concurrent
    writes against the same natural key); it is surfaced instead of
    retrying indefinitely so the caller can decide.
    """


@dataclass(frozen=True, slots=True)
class ObservationInput:
    """Data of a candidate observation, prior to deciding its revision."""

    listing_id: uuid.UUID
    source: str
    credential_scope: str
    external_listing_id: str
    session_date: date
    observation_type: ObservationType
    currency: str
    close: Decimal
    retrieved_at: datetime
    retrieval_policy_decision_id: uuid.UUID | None = None
    storage_policy_decision_id: uuid.UUID | None = None
    quality_status: QualityStatus = QualityStatus.OK
    open: Decimal | None = None
    high: Decimal | None = None
    low: Decimal | None = None
    adjusted_close: Decimal | None = None


@dataclass(frozen=True, slots=True)
class RecordOutcome:
    """Result of attempting to record an observation."""

    observation: Observation
    created: bool
    is_correction: bool


_VALUE_FIELDS = ("currency", "close", "open", "high", "low", "adjusted_close", "quality_status")
_MAX_REVISION_ATTEMPTS = 8


class ObservationStore:
    """Use cases for writing and reading the append-only history."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def record(self, data: ObservationInput) -> RecordOutcome:
        """Inserts the observation or detects that it is already recorded.

        Never executes an `UPDATE` over an existing `Observation` row: the
        only way to "correct" a value is a new row with a higher revision
        (tasks.md 4.1 § "corrections ... never a silent overwrite").
        """

        for _ in range(_MAX_REVISION_ATTEMPTS):
            current = self._current_revision(data)
            if current is not None and self._same_value(current, data):
                # Idempotent retry: the natural key and the value match
                # exactly what is already persisted.
                return RecordOutcome(observation=current, created=False, is_correction=False)

            next_revision = 1 if current is None else current.revision + 1
            candidate = Observation(
                listing_id=data.listing_id,
                source=data.source,
                credential_scope=data.credential_scope,
                external_listing_id=data.external_listing_id,
                session_date=data.session_date,
                observation_type=data.observation_type,
                revision=next_revision,
                currency=data.currency.upper(),
                close=data.close,
                open=data.open,
                high=data.high,
                low=data.low,
                adjusted_close=data.adjusted_close,
                quality_status=data.quality_status,
                retrieved_at=data.retrieved_at,
                retrieval_policy_decision_id=data.retrieval_policy_decision_id,
                storage_policy_decision_id=data.storage_policy_decision_id,
            )
            try:
                with self._session.begin_nested():
                    self._session.add(candidate)
                    self._session.flush()
            except IntegrityError:
                # Another process won the race for `next_revision` (or it
                # already existed). The rolled-back SAVEPOINT discards
                # `candidate`; we reread the current state on the next
                # iteration.
                continue
            return RecordOutcome(
                observation=candidate, created=True, is_correction=current is not None
            )

        raise RevisionRaceExhaustedError(
            f"Could not assign a revision for "
            f"{data.source}/{data.credential_scope}/{data.external_listing_id}/"
            f"{data.session_date}/{data.observation_type} after "
            f"{_MAX_REVISION_ATTEMPTS} attempts."
        )

    def _current_revision(self, data: ObservationInput) -> Observation | None:
        stmt = (
            select(Observation)
            .where(
                Observation.source == data.source,
                Observation.credential_scope == data.credential_scope,
                Observation.external_listing_id == data.external_listing_id,
                Observation.session_date == data.session_date,
                Observation.observation_type == data.observation_type,
            )
            .order_by(Observation.revision.desc())
            .limit(1)
        )
        return self._session.scalars(stmt).first()

    @staticmethod
    def _same_value(existing: Observation, data: ObservationInput) -> bool:
        return (
            existing.currency == data.currency.upper()
            and existing.close == data.close
            and existing.open == data.open
            and existing.high == data.high
            and existing.low == data.low
            and existing.adjusted_close == data.adjusted_close
            and existing.quality_status == data.quality_status
        )

    def current_for_key(
        self,
        *,
        source: str,
        credential_scope: str,
        external_listing_id: str,
        session_date: date,
        observation_type: ObservationType,
    ) -> Observation | None:
        """The current revision (highest `revision`) for a natural key."""

        stmt = (
            select(Observation)
            .where(
                Observation.source == source,
                Observation.credential_scope == credential_scope,
                Observation.external_listing_id == external_listing_id,
                Observation.session_date == session_date,
                Observation.observation_type == observation_type,
            )
            .order_by(Observation.revision.desc())
            .limit(1)
        )
        return self._session.scalars(stmt).first()

    def last_completed_session(
        self,
        *,
        source: str,
        credential_scope: str,
        external_listing_id: str,
        observation_type: ObservationType,
    ) -> date | None:
        """Last `session_date` with a persisted observation for the given
        key. Serves as a persistent recovery cursor: it does not depend on
        in-memory state, only on what is already stored
        (design.md § "Single scheduler with persistent queue").
        """

        stmt = select(func.max(Observation.session_date)).where(
            Observation.source == source,
            Observation.credential_scope == credential_scope,
            Observation.external_listing_id == external_listing_id,
            Observation.observation_type == observation_type,
        )
        return self._session.scalar(stmt)
