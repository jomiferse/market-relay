"""Translates a `RecoveryPlan` into idempotently enqueued jobs.

Joins `RecoveryPlanner` and `JobQueue`: each `RecoveryChunk` is enqueued as
a `PENDING` job with its own cursor; `WAITING_FOR_PUBLICATION` dates
generate a job in that same status, without counting as an error
(specs/market-data-ingestion/spec.md § "NAV not yet published"); `NO_SESSION`
dates generate no job and consume no quota.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from market_relay.domain.catalog.models import AssetClass
from market_relay.domain.ingestion.cursor import FetchCursor
from market_relay.domain.ingestion.planning import RecoveryLimits, RecoveryPlan, RecoveryPlanner
from market_relay.domain.ingestion.queue import EnqueueResult, JobQueue
from market_relay.domain.observations.models import JobStatus, ObservationType
from market_relay.ports.calendar import MarketCalendarPort

_JOB_TYPE_FETCH_RANGE = "fetch_range"


@dataclass(frozen=True, slots=True)
class DispatchResult:
    plan: RecoveryPlan
    enqueued: tuple[EnqueueResult, ...]
    waiting_job: EnqueueResult | None


def plan_and_enqueue(
    *,
    queue: JobQueue,
    calendar: MarketCalendarPort,
    limits: RecoveryLimits | None,
    listing_id: uuid.UUID,
    asset_class: AssetClass,
    venue: str,
    mic: str | None,
    source: str,
    credential_scope: str,
    external_listing_id: str,
    observation_type: ObservationType,
    last_completed_session: date | None,
    today: date,
    now: datetime,
    waiting_retry_seconds: int = 3600,
) -> DispatchResult:
    planner = RecoveryPlanner(calendar, limits)
    plan = planner.plan(
        asset_class=asset_class,
        venue=venue,
        mic=mic,
        last_completed_session=last_completed_session,
        today=today,
    )

    enqueued: list[EnqueueResult] = []
    for chunk in plan.chunks:
        cursor = FetchCursor(
            external_listing_id=external_listing_id,
            credential_scope=credential_scope,
            observation_type=observation_type,
            start=chunk.start,
            end=chunk.end,
        )
        dedupe_key = (
            f"{_JOB_TYPE_FETCH_RANGE}:{source}:{credential_scope}:{external_listing_id}:"
            f"{observation_type.value}:{chunk.start.isoformat()}:{chunk.end.isoformat()}"
        )
        result = queue.enqueue_idempotent(
            job_type=_JOB_TYPE_FETCH_RANGE,
            source=source,
            dedupe_key=dedupe_key,
            listing_id=listing_id,
            cursor=cursor.serialize(),
            run_at=now,
        )
        enqueued.append(result)

    waiting_job: EnqueueResult | None = None
    if plan.waiting_for_publication:
        first_waiting = plan.waiting_for_publication[0]
        last_waiting = plan.waiting_for_publication[-1]
        cursor = FetchCursor(
            external_listing_id=external_listing_id,
            credential_scope=credential_scope,
            observation_type=observation_type,
            start=first_waiting,
            end=last_waiting,
        )
        dedupe_key = (
            f"{_JOB_TYPE_FETCH_RANGE}:{source}:{credential_scope}:{external_listing_id}:"
            f"{observation_type.value}:waiting:{first_waiting.isoformat()}:{last_waiting.isoformat()}"
        )
        waiting_job = queue.enqueue_idempotent(
            job_type=_JOB_TYPE_FETCH_RANGE,
            source=source,
            dedupe_key=dedupe_key,
            listing_id=listing_id,
            cursor=cursor.serialize(),
            run_at=now + timedelta(seconds=waiting_retry_seconds),
        )
        if waiting_job.created:
            waiting_job.job.status = JobStatus.WAITING_FOR_PUBLICATION

    return DispatchResult(plan=plan, enqueued=tuple(enqueued), waiting_job=waiting_job)
