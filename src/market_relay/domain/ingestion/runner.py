"""Execution of an ingestion job: calendar, quota, fetch, validation.

Joins the neutral ports (`HistoricalPricePort`, `QuotaPort`), the
`PolicyGate`, `JobQueue`, and `ObservationStore` to process a `Job` in a
retry-safe way, isolating by instrument (specs/market-data-ingestion/spec.md).
Only `FakeMarketDataProvider` is integrated: no real source is instantiated
here or in this layer's tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from functools import partial
from typing import cast

from market_relay.domain.governance.credentials import sanitize_message
from market_relay.domain.governance.policy_gate import PolicyGate, PolicyNotAuthorizedError
from market_relay.domain.ingestion.cursor import FetchCursor, InvalidCursorError
from market_relay.domain.ingestion.error_codes import adapter_error_code
from market_relay.domain.ingestion.provider_execution import run_with_deadline
from market_relay.domain.ingestion.queue import JobQueue
from market_relay.domain.ingestion.validation import (
    MalformedObservationError,
    validate_raw_observation,
)
from market_relay.domain.observations.models import Job, JobStatus, QualityStatus
from market_relay.domain.observations.service import ObservationInput, ObservationStore
from market_relay.ports.historical import HistoricalPricePort
from market_relay.ports.quota import QuotaPort


@dataclass(frozen=True, slots=True)
class JobOutcome:
    status: JobStatus
    observations_recorded: int = 0
    observations_rejected: int = 0
    detail: str = ""


class IngestionRunner:
    """Processes a single `Job` up to a terminal or retry state."""

    def __init__(
        self,
        *,
        provider: HistoricalPricePort,
        policy_gate: PolicyGate,
        queue: JobQueue,
        store: ObservationStore,
        quota: QuotaPort | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        self._provider = provider
        self._quota = quota if quota is not None else cast("QuotaPort", provider)
        self._policy_gate = policy_gate
        self._queue = queue
        self._store = store
        self._timeout_seconds = timeout_seconds

    def process(self, job: Job, *, worker_id: str, now: datetime | None = None) -> JobOutcome:
        now = now or datetime.now(UTC)
        if job.status == JobStatus.PENDING:
            job = self._queue.claim_job(job, worker_id=worker_id, now=now)

        try:
            # RETRIEVE alone is not enough: ingestion persists what was
            # retrieved, so it requires RETRIEVE+STORE before calling the
            # provider or writing any observation
            # (specs/source-governance/spec.md § "Policy-governed
            # activation"). A STORE that is UNRESOLVED or DENIED prevents
            # both the fetch and the persistence.
            authorization = self._policy_gate.authorize_ingestion(job.source)
        except PolicyNotAuthorizedError as exc:
            self._queue.mark_failed(
                job,
                worker_id=worker_id,
                generation=job.generation,
                error=sanitize_message(str(exc)),
                now=now,
            )
            return JobOutcome(status=job.status, detail="policy_not_authorized")

        try:
            cursor = FetchCursor.parse(job.cursor)
        except InvalidCursorError as exc:
            self._queue.mark_failed(
                job,
                worker_id=worker_id,
                generation=job.generation,
                error=sanitize_message(str(exc)),
                now=now,
            )
            return JobOutcome(status=job.status, detail="invalid_cursor")

        generation = job.generation
        quota_status = self._quota.check(job.source)
        if quota_status.exhausted:
            # No further call is made to the provider: the job is deferred
            # directly to the known reset window
            # (specs/market-data-ingestion/spec.md § "Quota exhausted").
            self._queue.defer_for_quota(
                job,
                worker_id=worker_id,
                generation=generation,
                reset_at=quota_status.reset_at,
                now=now,
            )
            return JobOutcome(status=job.status, detail="quota_exhausted")

        self._queue.mark_running(job, worker_id=worker_id, generation=generation)

        try:
            raw_observations = run_with_deadline(
                partial(
                    self._provider.fetch_range,
                    external_listing_id=cursor.external_listing_id,
                    start=cursor.start,
                    end=cursor.end,
                ),
                timeout_seconds=self._timeout_seconds,
            )
        except Exception as exc:  # noqa: BLE001 - isolate any adapter failure
            # `job.last_error` never carries the provider's own exception
            # text: even after `sanitize_message`, a real adapter's free
            # text could still leak a secret in a shape the redaction
            # patterns do not cover. Only a bounded, generic code is stored.
            self._queue.mark_failed(
                job,
                worker_id=worker_id,
                generation=generation,
                error=adapter_error_code(exc),
                now=now,
            )
            return JobOutcome(status=job.status, detail="fetch_error")

        self._queue.assert_owned(job, worker_id=worker_id, generation=generation)
        self._quota.consume(job.source, cost=1)

        recorded = 0
        rejected = 0
        for raw in raw_observations:
            try:
                validate_raw_observation(
                    raw,
                    expected_external_listing_id=cursor.external_listing_id,
                    expected_start=cursor.start,
                    expected_end=cursor.end,
                )
            except MalformedObservationError:
                # Isolated per observation: a malformed row does not discard
                # the rest of this job's batch nor affect other
                # jobs/instruments.
                rejected += 1
                continue

            assert job.listing_id is not None
            outcome = self._store.record(
                ObservationInput(
                    listing_id=job.listing_id,
                    source=job.source,
                    credential_scope=cursor.credential_scope,
                    external_listing_id=raw.external_listing_id,
                    session_date=raw.session_date,
                    observation_type=raw.observation_type,
                    currency=raw.currency,
                    close=raw.close,
                    open=raw.open,
                    high=raw.high,
                    low=raw.low,
                    adjusted_close=raw.adjusted_close,
                    quality_status=QualityStatus.OK,
                    retrieved_at=now,
                    retrieval_policy_decision_id=authorization.retrieval_decision.id,
                    storage_policy_decision_id=authorization.storage_decision.id,
                )
            )
            if outcome.created:
                recorded += 1

        if rejected > 0 and recorded == 0:
            self._queue.mark_failed(
                job,
                worker_id=worker_id,
                generation=generation,
                error=f"{rejected} malformed observations out of {len(raw_observations)} received.",
                now=now,
            )
            return JobOutcome(
                status=job.status,
                observations_recorded=recorded,
                observations_rejected=rejected,
                detail="all_malformed",
            )

        self._queue.mark_done(job, worker_id=worker_id, generation=generation, now=now)
        return JobOutcome(
            status=job.status,
            observations_recorded=recorded,
            observations_rejected=rejected,
            detail="done",
        )
