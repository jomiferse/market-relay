"""Applies real append-only enforcement on `observations` via database
triggers and drops the `is_publishable` flag, which had become meaningless.

Before this migration, the append-only guarantee described in `tasks.md`
4.1 depended only on `ObservationStore`'s discipline (it never issues
`UPDATE`): any code with session access — a manual
`session.execute(update(...))`, a `session.delete(obs)`, an ad-hoc script —
could violate it without the database preventing it.
`ObservationStore.revoke_publishability` was itself an example of that
violation: it mutated `is_publishable=False` on already-persisted rows
with a real `UPDATE`. That function was removed;
`domain.observations.selection.ObservationSelector` now derives
publishability dynamically against the versioned `SourcePolicyDecision`
history (`PolicyGate.is_publication_authorized`) on every query, so no row
ever needs to be mutated when a source loses its publication authorization.
With that, the `is_publishable` column — always `True` from `INSERT`,
never read or written anywhere else — is unused; it is dropped so as not
to leave a misleading field in the schema.

With the column out of the way, this migration adds the real protection: a
`BEFORE UPDATE` trigger and a `BEFORE DELETE` trigger on `observations`
that abort the statement with an error, on both supported dialects
(PostgreSQL and SQLite). `INSERT` of a new revision is never affected:
only `UPDATE`/`DELETE` on an existing row are blocked.
`tests/unit/test_observation_immutability.py` demonstrates that a direct
`UPDATE` or `DELETE` (via raw SQL and via `session.delete()`/ORM attribute
mutation) fail, and that rows remain intact and readable.

Note for future migrations on `observations`: SQLite does not support full
`ALTER TABLE`, so any column change on this table will use "batch mode"
(table recreation), which discards the triggers created here. A future
migration using `op.batch_alter_table("observations")`
SHALL recreate these two triggers after the `batch` block.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-02 12:00:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

_PG_FUNCTION = """
CREATE OR REPLACE FUNCTION fn_observations_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION
        'observations is append-only: % not allowed (id=%)', TG_OP, OLD.id
        USING ERRCODE = '23000';
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;
"""

_PG_TRIGGER = """
CREATE TRIGGER trg_observations_append_only
BEFORE UPDATE OR DELETE ON observations
FOR EACH ROW
EXECUTE FUNCTION fn_observations_append_only();
"""

_PG_DROP_TRIGGER = "DROP TRIGGER IF EXISTS trg_observations_append_only ON observations"
_PG_DROP_FUNCTION = "DROP FUNCTION IF EXISTS fn_observations_append_only()"

_SQLITE_UPDATE_TRIGGER = """
CREATE TRIGGER trg_observations_no_update
BEFORE UPDATE ON observations
BEGIN
    SELECT RAISE(ABORT, 'observations is append-only: UPDATE not allowed');
END;
"""

_SQLITE_DELETE_TRIGGER = """
CREATE TRIGGER trg_observations_no_delete
BEFORE DELETE ON observations
BEGIN
    SELECT RAISE(ABORT, 'observations is append-only: DELETE not allowed');
END;
"""

_SQLITE_DROP_UPDATE_TRIGGER = "DROP TRIGGER IF EXISTS trg_observations_no_update"
_SQLITE_DROP_DELETE_TRIGGER = "DROP TRIGGER IF EXISTS trg_observations_no_delete"


def _dialect_name() -> str:
    bind = op.get_bind()
    return str(bind.dialect.name)


def upgrade() -> None:
    with op.batch_alter_table("observations", schema=None) as batch_op:
        batch_op.drop_column("is_publishable")

    dialect = _dialect_name()
    if dialect == "sqlite":
        op.execute(_SQLITE_UPDATE_TRIGGER)
        op.execute(_SQLITE_DELETE_TRIGGER)
    elif dialect == "postgresql":
        op.execute(_PG_FUNCTION)
        op.execute(_PG_TRIGGER)
    else:  # pragma: no cover - only these two dialects are supported
        raise RuntimeError(f"Unsupported dialect for append-only triggers: {dialect!r}")


def downgrade() -> None:
    dialect = _dialect_name()
    if dialect == "sqlite":
        op.execute(_SQLITE_DROP_UPDATE_TRIGGER)
        op.execute(_SQLITE_DROP_DELETE_TRIGGER)
    elif dialect == "postgresql":
        op.execute(_PG_DROP_TRIGGER)
        op.execute(_PG_DROP_FUNCTION)
    else:  # pragma: no cover - only these two dialects are supported
        raise RuntimeError(f"Unsupported dialect for append-only triggers: {dialect!r}")

    with op.batch_alter_table("observations", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("is_publishable", sa.Boolean(), nullable=False, server_default=sa.true())
        )
        batch_op.alter_column("is_publishable", server_default=None)
