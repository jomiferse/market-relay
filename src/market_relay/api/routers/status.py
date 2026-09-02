"""Operational and data status v1 endpoints.

tasks.md 5.1; `specs/operations/spec.md` § "Minimum observability". Exposes
only the sanitized subset fit for an external consumer: never credentials,
per-source quota, nor internal job names.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi import status as http_status
from sqlalchemy.orm import Session

from market_relay.adapters.registry import get_calendar_for_listing
from market_relay.api.deps import get_db, get_settings_dep, require_scope
from market_relay.api.schemas import (
    DataStatusOut,
    ErrorResponse,
    ObservationAvailability,
    OperationalStatusOut,
    SchedulerMetricsOut,
    SourceQuotaOut,
)
from market_relay.api.services.observation_view import (
    find_latest_observation,
    latest_publishable_session_date,
)
from market_relay.config import Settings
from market_relay.db.base import utcnow
from market_relay.domain.catalog.service import CatalogService
from market_relay.domain.governance.consumer_auth import ConsumerIdentity
from market_relay.domain.governance.policy_gate import PolicyGate
from market_relay.domain.ingestion.metrics import collect_scheduler_metrics
from market_relay.domain.ingestion.queue import JobQueue
from market_relay.domain.observations.models import ObservationType

CATALOG_READ_SCOPE = "catalog:read"
OPERATIONS_READ_SCOPE = "operations:read"
# Separate scope, deliberately not granted to Holdria by default
# (`config.settings.Settings.consumer_credentials`): the tasks.md 6.2
# metrics include the internal source name per job, which
# `/status/operations` omits on purpose for its only external consumer.
OPERATIONS_METRICS_SCOPE = "operations:metrics"

router = APIRouter(tags=["status"])


@router.get(
    "/status/operations",
    response_model=OperationalStatusOut,
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Sanitized scheduler operational status",
)
def operational_status(
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
    _identity: ConsumerIdentity = Depends(require_scope(OPERATIONS_READ_SCOPE)),
) -> OperationalStatusOut:
    queue = JobQueue(session)
    pending_jobs = queue.depth()
    oldest_age_seconds = queue.oldest_pending_age_seconds(now=utcnow())

    oldest_pending_seconds = None if oldest_age_seconds is None else max(int(oldest_age_seconds), 0)
    stalled = (
        oldest_pending_seconds is not None
        and oldest_pending_seconds > settings.stalled_job_threshold_seconds
    )

    return OperationalStatusOut(
        environment=settings.environment.value,
        pending_jobs=pending_jobs,
        oldest_pending_seconds=oldest_pending_seconds,
        stalled=stalled,
    )


@router.get(
    "/status/metrics",
    response_model=SchedulerMetricsOut,
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
    summary="Sanitized operational metrics for operators",
)
def scheduler_metrics(
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
    _identity: ConsumerIdentity = Depends(require_scope(OPERATIONS_METRICS_SCOPE)),
) -> SchedulerMetricsOut:
    """tasks.md 6.2; specs/operations/spec.md § "Minimum observability".

    Unlike `/status/operations`, this exposes the internal source name per
    job (an adapter identifier, never a credential) so an operator can
    identify which specific source is stalled, out of quota, or
    accumulating failures, without revealing any secret or a provider's
    raw error text.
    """

    snapshot = collect_scheduler_metrics(
        session=session,
        now=utcnow(),
        stalled_threshold_seconds=settings.stalled_job_threshold_seconds,
        sources=settings.enabled_sources,
    )
    return SchedulerMetricsOut(
        pending_jobs=snapshot.pending_jobs,
        pending_jobs_by_source=snapshot.pending_jobs_by_source,
        oldest_pending_seconds=snapshot.oldest_pending_seconds,
        done_jobs=snapshot.done_jobs,
        failed_jobs_by_source=snapshot.failed_jobs_by_source,
        quota_by_source=[
            SourceQuotaOut(
                source=quota.source,
                remaining=quota.remaining,
                limit=quota.limit,
                exhausted=quota.exhausted,
                error=quota.error,
            )
            for quota in snapshot.quota_by_source
        ],
        stalled_sources=list(snapshot.stalled_sources),
        scheduler_success_count=snapshot.scheduler_success_count,
        worker_success_count=snapshot.worker_success_count,
    )


@router.get(
    "/listings/{listing_id}/status",
    response_model=DataStatusOut,
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse, "description": "Listing does not exist."},
    },
    summary="Data status of a listing",
)
def data_status(
    listing_id: uuid.UUID,
    observation_type: ObservationType = Query(default=ObservationType.EOD_CLOSE),
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
    _identity: ConsumerIdentity = Depends(require_scope(CATALOG_READ_SCOPE)),
) -> DataStatusOut:
    """`last_effective_date` and `has_publishable_data` are both derived
    exclusively from observations that are currently publishable under the
    same `STORE`+`DISPLAY`+`REDISTRIBUTE` policy and `enabled_sources`
    priority as every value response
    (`api.services.observation_view.build_observation_out`): an
    observation from a `DENIED`, `UNRESOLVED`, or revoked source is never
    considered, even just to date-stamp it, so its mere existence never
    leaks through this endpoint (specs/consumer-api/spec.md § "Stored
    non-redistributable data").
    """

    listing = CatalogService(session).get_listing(listing_id)
    if listing is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Listing not found.")

    policy_gate = PolicyGate(session)
    last_effective_date = latest_publishable_session_date(
        session=session,
        listing=listing,
        observation_type=observation_type,
        settings=settings,
        policy_gate=policy_gate,
    )

    calendar = get_calendar_for_listing(mic=listing.mic, venue=listing.venue)
    latest = find_latest_observation(
        session=session,
        listing=listing,
        observation_type=observation_type,
        settings=settings,
        calendar=calendar,
    )

    return DataStatusOut(
        listing_id=listing_id,
        observation_type=observation_type,
        last_effective_date=last_effective_date,
        has_publishable_data=latest.availability is ObservationAvailability.OK,
    )
