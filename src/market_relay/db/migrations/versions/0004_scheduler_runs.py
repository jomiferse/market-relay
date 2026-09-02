"""Adds `scheduler_runs`: a durable record of each execution of the single
scheduled entry point.

`tasks.md` 6.1 and `specs/operations/spec.md` § "Minimum observability"
require exposing "successful executions of the scheduler and worker", not
only the count of individually successful jobs. Before this migration,
there was no persistent record of a *whole cycle execution* independent of
its jobs: a phase that crashed before processing anything left no durable
trace at all, so an operator had no way to distinguish "the scheduler
never ran" from "the scheduler ran and had nothing to do".

One row is written per execution, with two nullable status columns —
`scheduler_status` for the refresh-and-dispatch phase and `worker_status`
for the job-processing phase — filled in independently as each phase
completes (`domain.ingestion.scheduler_runs.SchedulerRunRecorder`). Both
columns are populated on their own connection, independent of the
transaction the cycle's own work runs in, so a rollback of that work never
erases an already-recorded phase outcome.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-02 15:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "scheduler_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column(
            "scheduler_status",
            sa.Enum("SUCCESS", "FAILURE", name="schedulerrunstatus", native_enum=False, length=16),
            nullable=True,
        ),
        sa.Column(
            "worker_status",
            sa.Enum("SUCCESS", "FAILURE", name="schedulerrunstatus", native_enum=False, length=16),
            nullable=True,
        ),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scheduler_runs")),
    )


def downgrade() -> None:
    op.drop_table("scheduler_runs")
