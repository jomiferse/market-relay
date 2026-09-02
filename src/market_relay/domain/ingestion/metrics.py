"""Sanitized operational metrics of the scheduler and queue (tasks.md 6.2;
specs/operations/spec.md § "Minimum observability").

Only aggregate counts, ages and quota remainders are exposed here: never
`Job.cursor`, `Job.last_error`, or any other free-text field that could
carry an already-sanitized but still specific provider detail. `source` is
an internal identifier of a registered adapter (e.g. "fake"), never a
credential or a secret, so it is safe to expose to an operational consumer
holding the `operations:metrics` scope — the Holdria-facing data API
(`/status/operations`) still deliberately omits the source name, see
`api.routers.status`.

A quota adapter failure never surfaces `str(exc)`: even after
`sanitize_message`, a provider's free text could still carry a secret in a
shape the redaction patterns do not cover. `error` is always one of the
bounded, generic codes from `domain.ingestion.error_codes`.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import InstrumentedAttribute, Session

from market_relay.adapters.registry import get_quota_port
from market_relay.domain.ingestion.error_codes import adapter_error_code
from market_relay.domain.ingestion.queue import JobQueue
from market_relay.domain.observations.models import SchedulerRun, SchedulerRunStatus


@dataclass(frozen=True, slots=True)
class SourceQuotaSnapshot:
    """Quota state of a single source.

    `remaining`/`limit` come directly from the adapter's `QuotaPort`, which
    never exposes the secret used to authenticate against the provider —
    only that provider's own quota counters. If the adapter is not
    registered or fails when queried, `error` carries a bounded, generic
    code (`domain.ingestion.error_codes.adapter_error_code`) — never the
    provider's own exception text, sanitized or not — and the counters stay
    `None`, without interrupting the other sources.
    """

    source: str
    remaining: int | None
    limit: int | None
    exhausted: bool
    error: str | None = None


@dataclass(frozen=True, slots=True)
class SchedulerMetricsSnapshot:
    """Sanitized snapshot of `specs/operations/spec.md` § "Minimum
    observability": queue depth, oldest pending job age, successes, failures
    by source, quota state and stalled sources.
    """

    pending_jobs: int
    pending_jobs_by_source: dict[str, int]
    oldest_pending_seconds: float | None
    done_jobs: int
    failed_jobs_by_source: dict[str, int]
    quota_by_source: tuple[SourceQuotaSnapshot, ...]
    # Sources whose oldest pending job exceeds the configured threshold:
    # the signal that lets an operator detect the delay and identify the
    # source without revealing any credential (specs/operations/spec.md §
    # "Stalled jobs").
    stalled_sources: tuple[str, ...]
    # Durable counts backed by `scheduler_runs` (tasks.md 6.1;
    # specs/operations/spec.md § "Minimum observability": "successful
    # executions of the scheduler and worker"). Unlike `done_jobs` (a count
    # of individually successful jobs), these count whole executions of
    # each bounded phase of the single entry point, including a phase that
    # crashed before processing any job at all.
    scheduler_success_count: int
    worker_success_count: int


def collect_scheduler_metrics(
    *,
    session: Session,
    now: datetime,
    stalled_threshold_seconds: int,
    sources: Iterable[str],
) -> SchedulerMetricsSnapshot:
    """Builds the sanitized snapshot for the given sources (typically
    `settings.enabled_sources`).

    Isolated per source: a quota adapter that fails or is not registered
    never prevents computing the metrics for the other sources
    (specs/operations/spec.md § "Safe degraded operation").
    """

    queue = JobQueue(session)
    pending_by_source = queue.pending_by_source()
    age_by_source = queue.oldest_pending_age_by_source(now=now)

    quota_snapshots: list[SourceQuotaSnapshot] = []
    for source in sources:
        try:
            status = get_quota_port(source).check(source)
        except Exception as exc:  # noqa: BLE001 - isolate an adapter that fails when queried
            quota_snapshots.append(
                SourceQuotaSnapshot(
                    source=source,
                    remaining=None,
                    limit=None,
                    exhausted=False,
                    error=adapter_error_code(exc),
                )
            )
            continue

        quota_snapshots.append(
            SourceQuotaSnapshot(
                source=source,
                remaining=status.remaining,
                limit=status.limit,
                exhausted=status.exhausted,
            )
        )

    stalled_sources = tuple(
        sorted(source for source, age in age_by_source.items() if age > stalled_threshold_seconds)
    )

    return SchedulerMetricsSnapshot(
        pending_jobs=sum(pending_by_source.values()),
        pending_jobs_by_source=pending_by_source,
        oldest_pending_seconds=max(age_by_source.values()) if age_by_source else None,
        done_jobs=queue.done_count(),
        failed_jobs_by_source=queue.failed_by_source(),
        quota_by_source=tuple(quota_snapshots),
        stalled_sources=stalled_sources,
        scheduler_success_count=_count_runs_with_status(session, SchedulerRun.scheduler_status),
        worker_success_count=_count_runs_with_status(session, SchedulerRun.worker_status),
    )


def _count_runs_with_status(
    session: Session, status_column: InstrumentedAttribute[SchedulerRunStatus | None]
) -> int:
    """Count of durable `scheduler_runs` rows whose given phase column
    recorded `SUCCESS`. `status_column` is `SchedulerRun.scheduler_status`
    or `SchedulerRun.worker_status` — the two independent execution signals
    required by specs/operations/spec.md § "Minimum observability".
    """

    stmt = select(func.count(SchedulerRun.id)).where(status_column == SchedulerRunStatus.SUCCESS)
    return session.scalar(stmt) or 0
