"""Observation revisions and idempotent enqueueing.

`tasks.md` 4.1 requires that a correction be preserved as a new revision,
never as a silent overwrite: adds `observations.revision` and extends the
natural idempotency key to include it, so that
`(source, credential_scope, external_listing_id, session_date,
observation_type)` can have several rows — one per revision — while each
`(natural key, revision)` stays unique.

`tasks.md` 4.5 requires idempotent enqueueing: adds a unique
`jobs.dedupe_key`, so that re-enqueueing the same logical job (source +
listing + range) is a no-op instead of duplicating the row.

On a database with preexisting data (several `jobs` already inserted by
`0001`, before this column), adding `dedupe_key` with a shared
`server_default` (`''`) and creating the unique constraint in the same step
would fail as soon as there was more than one row: they would all share the
same default value. That's why the backfill `UPDATE` runs *between* adding
the column and creating the unique constraint, assigning each preexisting
row a deterministic, unique `dedupe_key` derived from its `id` (primary
key, already unique) before the constraint exists. A new job enqueued after
this migration always receives its real `dedupe_key` from
`JobQueue.enqueue_idempotent`; the backfill value only identifies legacy
jobs that will never again be deduplicated against a re-enqueue (there was
no `dedupe_key` when they were created), which is acceptable because it is
not a regression relative to the behavior before this migration.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-01 22:31:35.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("observations", schema=None) as batch_op:
        batch_op.drop_constraint("uq_observations_idempotency_key", type_="unique")
        batch_op.add_column(sa.Column("revision", sa.Integer(), nullable=False, server_default="1"))
        batch_op.alter_column("revision", server_default=None)
        batch_op.create_unique_constraint(
            "uq_observations_idempotency_key",
            [
                "source",
                "credential_scope",
                "external_listing_id",
                "session_date",
                "observation_type",
                "revision",
            ],
        )

    with op.batch_alter_table("jobs", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("dedupe_key", sa.String(length=256), nullable=False, server_default="")
        )

    # Backfill: each preexisting row (all sharing the `server_default`
    # `''` at this point) receives a deterministic, unique `dedupe_key`
    # derived from its `id`, so that the unique constraint below does not
    # fail on a database with several `jobs` already inserted.
    jobs_table = sa.table(
        "jobs",
        sa.column("id", sa.Uuid()),
        sa.column("dedupe_key", sa.String(length=256)),
    )
    op.execute(
        jobs_table.update()
        .where(jobs_table.c.dedupe_key == "")
        .values(dedupe_key=sa.literal("legacy-job:") + sa.cast(jobs_table.c.id, sa.String()))
    )

    with op.batch_alter_table("jobs", schema=None) as batch_op:
        batch_op.alter_column("dedupe_key", server_default=None)
        batch_op.create_unique_constraint("uq_jobs_dedupe_key", ["dedupe_key"])


def downgrade() -> None:
    with op.batch_alter_table("jobs", schema=None) as batch_op:
        batch_op.drop_constraint("uq_jobs_dedupe_key", type_="unique")
        batch_op.drop_column("dedupe_key")

    with op.batch_alter_table("observations", schema=None) as batch_op:
        batch_op.drop_constraint("uq_observations_idempotency_key", type_="unique")
        batch_op.drop_column("revision")
        batch_op.create_unique_constraint(
            "uq_observations_idempotency_key",
            [
                "source",
                "credential_scope",
                "external_listing_id",
                "session_date",
                "observation_type",
            ],
        )
