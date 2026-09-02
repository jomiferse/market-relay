"""Durable recording of scheduler and worker execution outcomes (tasks.md
6.1; specs/operations/spec.md § "Minimum observability": "successful
executions of the scheduler and worker").

`SchedulerRunRecorder` writes on the same session as the cycle's own work,
one commit per phase boundary, rather than through a second, independent
connection: SQLite — a supported deployment dialect alongside PostgreSQL,
see `domain.ingestion.queue` — allows only one writer at a time, so a
second connection attempting to write while the cycle's session still holds
an open transaction would itself fail with "database is locked" instead of
recording anything. Each `commit()` here durably persists the run row up to
that point before the next phase runs, so a crash partway through the cycle
never loses a phase outcome that had already completed: that is the
transactional guarantee behind the durable "successful scheduler/worker
execution" signal, achieved with disciplined commit points on a single
connection rather than cross-connection writes.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from market_relay.db.base import utcnow
from market_relay.domain.observations.models import SchedulerRun, SchedulerRunStatus


class SchedulerRunRecorder:
    """Persists the outcome of the scheduler and worker phases of one
    execution, committing the caller's session at each phase boundary.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def start(self, *, now: datetime) -> SchedulerRun:
        """Creates and durably commits a new run row before any phase runs."""

        run = SchedulerRun(started_at=now)
        self._session.add(run)
        self._session.commit()
        return run

    def record_scheduler_result(
        self, run: SchedulerRun, *, status: SchedulerRunStatus, error_code: str | None = None
    ) -> None:
        """Records the refresh-and-dispatch phase outcome."""

        run.scheduler_status = status
        if error_code is not None:
            run.error_code = error_code
        self._session.commit()

    def record_worker_result(
        self, run: SchedulerRun, *, status: SchedulerRunStatus, error_code: str | None = None
    ) -> None:
        """Records the job-processing phase outcome and marks the run
        finished: the worker phase is always the last one in a cycle.
        """

        run.worker_status = status
        run.finished_at = utcnow()
        if error_code is not None:
            run.error_code = error_code
        self._session.commit()
