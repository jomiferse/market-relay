"""Single scheduled entry point (design.md § "Single scheduler with
persistent queue"; specs/operations/spec.md § "Portable scheduled entry
point").

Each invocation runs one bounded cycle
(`domain.ingestion.scheduler_service.run_scheduler_cycle`): calendar refresh
and dispatch of pending recovery, followed by processing bounded by
`scheduler_batch_size`. No phase depends on in-process memory, so this
entry point can be re-run — same cron, same container relaunched after a
crash — without duplicating jobs or observations (tasks.md 6.1).
"""

from __future__ import annotations

import logging

from market_relay.config import Settings, get_settings
from market_relay.db.base import utcnow
from market_relay.db.session import (
    build_session_factory,
    create_engine_from_settings,
    session_scope,
)
from market_relay.domain.ingestion.scheduler_service import run_scheduler_cycle

logger = logging.getLogger("market_relay.scheduler")

_WORKER_ID = "scheduler"

# Max number of listings per source whose calendar is refreshed and for
# which recovery is dispatched in a single execution: bounds the cost of
# the refresh phase even with a large catalog (specs/operations/spec.md §
# "Portable scheduled entry point").
_MAX_LISTINGS_REFRESHED_PER_SOURCE = 200


def run(settings: Settings | None = None) -> None:
    settings = settings if settings is not None else get_settings()
    logging.basicConfig(level=logging.INFO)
    logger.info(
        "market-relay-scheduler started (environment=%s, sources=%s, batch=%d)",
        settings.environment,
        ",".join(settings.enabled_sources),
        settings.scheduler_batch_size,
    )

    engine = create_engine_from_settings(settings)
    session_factory = build_session_factory(engine)
    try:
        with session_scope(session_factory) as session:
            result = run_scheduler_cycle(
                session=session,
                settings=settings,
                now=utcnow(),
                max_listings_per_source=_MAX_LISTINGS_REFRESHED_PER_SOURCE,
                worker_id=_WORKER_ID,
            )

        # Sanitized signal of a "successful scheduler execution"
        # (specs/operations/spec.md § "Minimum observability"): nothing here
        # is a job identifier, a cursor, or a secret.
        logger.info(
            "market-relay-scheduler completed: listings_considered=%d "
            "jobs_enqueued=%d jobs_claimed=%d done=%d "
            "waiting_for_publication=%d deferred_for_quota=%d "
            "retrying=%d failed_terminal=%d",
            result.refresh.listings_considered,
            result.refresh.jobs_enqueued,
            result.processed.jobs_claimed,
            result.processed.jobs_done,
            result.processed.jobs_waiting,
            result.processed.jobs_deferred_quota,
            result.processed.jobs_retrying,
            result.processed.jobs_failed_terminal,
        )
        for error in result.refresh.refresh_errors:
            logger.warning("market-relay-scheduler: isolated failure during refresh: %s", error)
    finally:
        engine.dispose()


if __name__ == "__main__":
    run()
