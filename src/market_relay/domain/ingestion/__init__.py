"""Bounded recovery, persistent queue, and ingestion execution (tasks.md 4)."""

from market_relay.domain.ingestion.cursor import FetchCursor, InvalidCursorError
from market_relay.domain.ingestion.dispatch import DispatchResult, plan_and_enqueue
from market_relay.domain.ingestion.error_codes import (
    ADAPTER_ERROR,
    UNKNOWN_SOURCE,
    adapter_error_code,
)
from market_relay.domain.ingestion.metrics import (
    SchedulerMetricsSnapshot,
    SourceQuotaSnapshot,
    collect_scheduler_metrics,
)
from market_relay.domain.ingestion.planning import (
    RecoveryChunk,
    RecoveryLimits,
    RecoveryPlan,
    RecoveryPlanner,
)
from market_relay.domain.ingestion.queue import EnqueueResult, JobQueue, backoff_seconds
from market_relay.domain.ingestion.runner import IngestionRunner, JobOutcome
from market_relay.domain.ingestion.scheduler_runs import SchedulerRunRecorder
from market_relay.domain.ingestion.scheduler_service import (
    DEFAULT_CREDENTIAL_SCOPE,
    ProcessOutcome,
    RefreshOutcome,
    SchedulerCycleResult,
    claim_and_process,
    refresh_and_dispatch,
    run_scheduler_cycle,
)
from market_relay.domain.ingestion.validation import (
    MalformedObservationError,
    validate_raw_observation,
)

__all__ = [
    "FetchCursor",
    "InvalidCursorError",
    "DispatchResult",
    "plan_and_enqueue",
    "ADAPTER_ERROR",
    "UNKNOWN_SOURCE",
    "adapter_error_code",
    "RecoveryChunk",
    "RecoveryLimits",
    "RecoveryPlan",
    "RecoveryPlanner",
    "EnqueueResult",
    "JobQueue",
    "backoff_seconds",
    "IngestionRunner",
    "JobOutcome",
    "MalformedObservationError",
    "validate_raw_observation",
    "SchedulerMetricsSnapshot",
    "SourceQuotaSnapshot",
    "collect_scheduler_metrics",
    "SchedulerRunRecorder",
    "DEFAULT_CREDENTIAL_SCOPE",
    "ProcessOutcome",
    "RefreshOutcome",
    "SchedulerCycleResult",
    "claim_and_process",
    "refresh_and_dispatch",
    "run_scheduler_cycle",
]
