"""Orchestrates the single scheduled entry point (tasks.md 6.1;
design.md § "Single scheduler with persistent queue";
specs/operations/spec.md § "Portable scheduled entry point").

Each cycle runs two bounded phases over the persistent queue:

1. **Refresh and dispatch**: for each enabled source, up to
   `max_listings_per_source` active listings of that source have their
   calendar refreshed and their pending recovery enqueued idempotently
   (`plan_and_enqueue`). No phase scans the whole catalog without a bound.
2. **Processing**: up to `scheduler_batch_size` eligible `PENDING` jobs are
   claimed and processed with `IngestionRunner`.

No phase depends on in-process memory: the recovery cursor
(`ObservationStore.last_completed_session`), claims and retries all live in
the database, so a repeated execution — same cron, same process relaunched
after a crash — is safe and never duplicates jobs or observations. A
failure isolated to one source, listing or job is recorded and never
interrupts the rest of the cycle (specs/operations/spec.md § "Safe degraded
operation").

Each of the two phases is also committed independently
(`run_scheduler_cycle`) and its outcome recorded durably through
`SchedulerRunRecorder`: a crash during processing never rolls back a
refresh phase that already completed, and the "successful scheduler and
worker execution" metrics required by specs/operations/spec.md §
"Minimum observability" reflect exactly which phase actually finished, even
when the other one failed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from market_relay.adapters.registry import (
    get_calendar_for_listing,
    get_historical_price_port,
    get_quota_port,
)
from market_relay.config import Settings
from market_relay.domain.catalog.models import AssetClass, ExternalIdentity, Listing
from market_relay.domain.governance.policy_gate import PolicyGate
from market_relay.domain.ingestion.dispatch import plan_and_enqueue
from market_relay.domain.ingestion.error_codes import adapter_error_code
from market_relay.domain.ingestion.planning import RecoveryLimits
from market_relay.domain.ingestion.queue import JobQueue, StaleJobClaimError
from market_relay.domain.ingestion.runner import IngestionRunner
from market_relay.domain.ingestion.scheduler_runs import SchedulerRunRecorder
from market_relay.domain.observations.models import JobStatus, ObservationType, SchedulerRunStatus
from market_relay.domain.observations.service import ObservationStore

# Single credential scope, while there is only one account per source
# (design.md § "Isolated central credentials"): the model already
# supports several scopes, but the scheduler only needs to distinguish them
# the day more than one credential exists for the same source.
DEFAULT_CREDENTIAL_SCOPE = "default"

_SCHEDULER_WORKER_ID = "scheduler"


def _observation_type_for(asset_class: AssetClass) -> ObservationType:
    """Funds use the NAV date; equities, ETFs and crypto use the EOD close
    (design.md § "Different strategies by frequency").
    """

    return ObservationType.NAV if asset_class is AssetClass.FUND else ObservationType.EOD_CLOSE


@dataclass(frozen=True, slots=True)
class RefreshOutcome:
    """Result of the refresh-and-dispatch phase."""

    listings_considered: int = 0
    jobs_enqueued: int = 0
    # `"{source}: {bounded generic code}"` for a calendar or dispatch
    # failure isolated per listing/source — never the provider's own
    # exception text, sanitized or not (`domain.ingestion.error_codes`).
    refresh_errors: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ProcessOutcome:
    """Result of the bounded job-processing phase."""

    jobs_claimed: int = 0
    jobs_done: int = 0
    jobs_waiting: int = 0
    jobs_deferred_quota: int = 0
    # Jobs that exhausted retries and ended up `FAILED` (terminal).
    jobs_failed_terminal: int = 0
    # Jobs that failed but remain `PENDING` for a bounded retry with backoff
    # (specs/market-data-ingestion/spec.md § "Quotas and partial failures"):
    # not a success, but not the terminal failure either.
    jobs_retrying: int = 0


@dataclass(frozen=True, slots=True)
class SchedulerCycleResult:
    """Full result of one execution of the single entry point."""

    refresh: RefreshOutcome = field(default_factory=RefreshOutcome)
    processed: ProcessOutcome = field(default_factory=ProcessOutcome)


def refresh_and_dispatch(
    *,
    session: Session,
    settings: Settings,
    now: datetime,
    max_listings_per_source: int,
    recovery_limits: RecoveryLimits | None = None,
) -> RefreshOutcome:
    """Refreshes calendars and dispatches pending recovery in a bounded,
    idempotent way.

    For each enabled source, considers up to `max_listings_per_source`
    listings with a currently valid external identity in that source. The
    recovery cursor is always `ObservationStore.last_completed_session`
    —durable state, never in-process memory— so re-running this function
    against the same database state recomputes the same pending range, and
    `plan_and_enqueue` enqueues it idempotently: no repetition ever produces
    a duplicate job (tasks.md 6.1).
    """

    queue = JobQueue(session)
    store = ObservationStore(session)
    today = now.date()

    listings_considered = 0
    jobs_enqueued = 0
    errors: list[str] = []

    for source in settings.enabled_sources:
        try:
            get_historical_price_port(source)
            get_quota_port(source)
        except Exception as exc:  # noqa: BLE001 - isolated per source
            errors.append(f"{source}: {adapter_error_code(exc)}")
            continue

        identities = session.scalars(
            select(ExternalIdentity)
            .where(
                ExternalIdentity.source == source,
                (ExternalIdentity.valid_to.is_(None)) | (ExternalIdentity.valid_to >= today),
            )
            .order_by(ExternalIdentity.listing_id, ExternalIdentity.valid_from)
            .limit(max_listings_per_source)
        ).all()

        for identity in identities:
            listings_considered += 1
            listing = session.get(Listing, identity.listing_id)
            if listing is None:  # pragma: no cover - defensive, the FK guarantees existence
                continue

            try:
                observation_type = _observation_type_for(listing.instrument.asset_class)
                last_completed = store.last_completed_session(
                    source=source,
                    credential_scope=DEFAULT_CREDENTIAL_SCOPE,
                    external_listing_id=identity.external_id,
                    observation_type=observation_type,
                )
                dispatch = plan_and_enqueue(
                    queue=queue,
                    calendar=get_calendar_for_listing(mic=listing.mic, venue=listing.venue),
                    limits=recovery_limits,
                    listing_id=listing.id,
                    asset_class=listing.instrument.asset_class,
                    venue=listing.venue,
                    mic=listing.mic,
                    source=source,
                    credential_scope=DEFAULT_CREDENTIAL_SCOPE,
                    external_listing_id=identity.external_id,
                    observation_type=observation_type,
                    last_completed_session=last_completed,
                    today=today,
                    now=now,
                    waiting_retry_seconds=settings.waiting_publication_retry_seconds,
                )
            except Exception as exc:  # noqa: BLE001 - isolated per listing/source
                errors.append(f"{source}: {adapter_error_code(exc)}")
                continue

            jobs_enqueued += sum(1 for result in dispatch.enqueued if result.created)
            if dispatch.waiting_job is not None and dispatch.waiting_job.created:
                jobs_enqueued += 1

    return RefreshOutcome(
        listings_considered=listings_considered,
        jobs_enqueued=jobs_enqueued,
        refresh_errors=tuple(errors),
    )


def claim_and_process(
    *,
    session: Session,
    settings: Settings,
    now: datetime,
    batch_size: int,
    worker_id: str = _SCHEDULER_WORKER_ID,
) -> ProcessOutcome:
    """Claims and processes up to `batch_size` eligible `PENDING` jobs.

    Uses the atomic claim of `JobQueue.claim_next`: under concurrent
    workers each job is won by at most one
    (specs/market-data-ingestion/spec.md § "Idempotence and concurrency").
    An unexpected failure resolving the adapter or processing a given job is
    isolated with `JobQueue.mark_failed` and never interrupts the rest of
    the batch (specs/operations/spec.md § "Safe degraded operation").
    """

    queue = JobQueue(session)
    store = ObservationStore(session)
    policy_gate = PolicyGate(session)

    claimed = queue.claim_next(
        worker_id=worker_id,
        now=now,
        limit=batch_size,
        lease_seconds=settings.job_lease_seconds,
    )

    outcome = ProcessOutcome(jobs_claimed=len(claimed))
    done = waiting = quota_deferred = failed_terminal = retrying = 0

    for job in claimed:
        try:
            historical = get_historical_price_port(job.source)
            quota = get_quota_port(job.source)
            runner = IngestionRunner(
                provider=historical,
                quota=quota,
                policy_gate=policy_gate,
                queue=queue,
                store=store,
                timeout_seconds=settings.provider_timeout_seconds,
            )
            result = runner.process(job, worker_id=worker_id, now=now)
        except StaleJobClaimError:
            # A concurrent recovery fenced this worker. It must not mutate
            # the current owner's retry or completion state.
            continue
        except Exception as exc:  # noqa: BLE001 - an unexpected failure must not stop the cycle
            # This branch catches truly unforeseen failures, including
            # adapter resolution and provider construction: `str(exc)` here
            # is exactly as untrusted as any other provider-originated text
            # (see error_codes.adapter_error_code), so it must never be
            # persisted even through `sanitize_message`. Only the bounded,
            # generic code is stored.
            queue.mark_failed(
                job,
                worker_id=worker_id,
                generation=job.generation,
                error=adapter_error_code(exc),
                now=now,
            )
            failed_terminal += 1 if job.status == JobStatus.FAILED else 0
            retrying += 1 if job.status == JobStatus.PENDING else 0
            continue

        if result.detail == "quota_exhausted":
            quota_deferred += 1
        elif job.status == JobStatus.DONE:
            done += 1
        elif job.status == JobStatus.WAITING_FOR_PUBLICATION:
            waiting += 1
        elif job.status == JobStatus.FAILED:
            failed_terminal += 1
        elif job.status == JobStatus.PENDING:
            retrying += 1
        # CLAIMED/RUNNING should never survive `process`; if it ever did
        # (a future bug), the next cycle picks the job up again without
        # losing it.

    return ProcessOutcome(
        jobs_claimed=outcome.jobs_claimed,
        jobs_done=done,
        jobs_waiting=waiting,
        jobs_deferred_quota=quota_deferred,
        jobs_failed_terminal=failed_terminal,
        jobs_retrying=retrying,
    )


def run_scheduler_cycle(
    *,
    session: Session,
    settings: Settings,
    now: datetime,
    max_listings_per_source: int,
    worker_id: str = _SCHEDULER_WORKER_ID,
    recovery_limits: RecoveryLimits | None = None,
) -> SchedulerCycleResult:
    """Runs one full cycle: refresh+dispatch followed by bounded processing.

    `session` is committed right after each phase, not only once at the
    very end: the refresh phase's own persistence (job dispatch) is durable
    before the processing phase even starts, so a failure isolated to
    processing can never roll back recovery that already succeeded. If the
    process is interrupted between phases, the next invocation resumes from
    that durable state, never from memory (tasks.md 6.1).

    Each phase's outcome is also recorded through `SchedulerRunRecorder`,
    committing `session` at each phase boundary: this is the durable
    "successful scheduler/worker execution" signal required by
    specs/operations/spec.md § "Minimum observability"
    (`domain.ingestion.metrics.collect_scheduler_metrics`). Both phases
    already isolate every failure at the source/listing/job level and
    should never raise; a phase escaping that isolation (a systemic
    failure, e.g. the database itself) is still recorded as a durable
    `FAILURE` before the exception propagates, rather than silently
    disappearing along with the rolled-back work.
    """

    recorder = SchedulerRunRecorder(session)
    run = recorder.start(now=now)

    try:
        refresh = refresh_and_dispatch(
            session=session,
            settings=settings,
            now=now,
            max_listings_per_source=max_listings_per_source,
            recovery_limits=recovery_limits,
        )
    except Exception as exc:  # noqa: BLE001 - last-resort durable failure signal
        session.rollback()
        recorder.record_scheduler_result(
            run, status=SchedulerRunStatus.FAILURE, error_code=adapter_error_code(exc)
        )
        recorder.record_worker_result(run, status=SchedulerRunStatus.FAILURE)
        raise

    session.commit()
    recorder.record_scheduler_result(run, status=SchedulerRunStatus.SUCCESS)

    try:
        processed = claim_and_process(
            session=session,
            settings=settings,
            now=now,
            batch_size=settings.scheduler_batch_size,
            worker_id=worker_id,
        )
    except Exception as exc:  # noqa: BLE001 - last-resort durable failure signal
        session.rollback()
        recorder.record_worker_result(
            run, status=SchedulerRunStatus.FAILURE, error_code=adapter_error_code(exc)
        )
        raise

    session.commit()
    recorder.record_worker_result(run, status=SchedulerRunStatus.SUCCESS)

    return SchedulerCycleResult(refresh=refresh, processed=processed)
