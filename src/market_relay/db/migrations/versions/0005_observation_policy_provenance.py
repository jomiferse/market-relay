"""Add immutable acquisition-policy provenance to observations.

The columns are nullable only for rows created before this migration. All new
application writes provide both references. SQLite batch alteration recreates
the table, so its append-only triggers are restored explicitly.

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-03 10:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

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
_SQLITE_POLICY_UPDATE_TRIGGER = """
CREATE TRIGGER trg_source_policy_decisions_no_update
BEFORE UPDATE ON source_policy_decisions
BEGIN
    SELECT RAISE(ABORT, 'source policy decisions are append-only: UPDATE not allowed');
END;
"""
_SQLITE_POLICY_DELETE_TRIGGER = """
CREATE TRIGGER trg_source_policy_decisions_no_delete
BEFORE DELETE ON source_policy_decisions
BEGIN
    SELECT RAISE(ABORT, 'source policy decisions are append-only: DELETE not allowed');
END;
"""
_PG_POLICY_FUNCTION = """
CREATE OR REPLACE FUNCTION fn_source_policy_decisions_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'source policy decisions are append-only: % not allowed', TG_OP
        USING ERRCODE = '23000';
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;
"""
_PG_POLICY_TRIGGER = """
CREATE TRIGGER trg_source_policy_decisions_append_only
BEFORE UPDATE OR DELETE ON source_policy_decisions
FOR EACH ROW EXECUTE FUNCTION fn_source_policy_decisions_append_only();
"""


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    with op.batch_alter_table("observations", schema=None) as batch_op:
        batch_op.add_column(sa.Column("retrieval_policy_decision_id", sa.Uuid(), nullable=True))
        batch_op.add_column(sa.Column("storage_policy_decision_id", sa.Uuid(), nullable=True))
        batch_op.create_foreign_key(
            "fk_observations_retrieval_policy",
            "source_policy_decisions",
            ["retrieval_policy_decision_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch_op.create_foreign_key(
            "fk_observations_storage_policy",
            "source_policy_decisions",
            ["storage_policy_decision_id"],
            ["id"],
            ondelete="RESTRICT",
        )
    if dialect == "sqlite":
        op.execute(_SQLITE_UPDATE_TRIGGER)
        op.execute(_SQLITE_DELETE_TRIGGER)
        op.execute(_SQLITE_POLICY_UPDATE_TRIGGER)
        op.execute(_SQLITE_POLICY_DELETE_TRIGGER)
    elif dialect == "postgresql":
        op.execute(_PG_POLICY_FUNCTION)
        op.execute(_PG_POLICY_TRIGGER)


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_source_policy_decisions_no_update")
        op.execute("DROP TRIGGER IF EXISTS trg_source_policy_decisions_no_delete")
    elif dialect == "postgresql":
        op.execute(
            "DROP TRIGGER IF EXISTS trg_source_policy_decisions_append_only "
            "ON source_policy_decisions"
        )
        op.execute("DROP FUNCTION IF EXISTS fn_source_policy_decisions_append_only()")
    with op.batch_alter_table("observations", schema=None) as batch_op:
        batch_op.drop_constraint(
            "fk_observations_storage_policy",
            type_="foreignkey",
        )
        batch_op.drop_constraint(
            "fk_observations_retrieval_policy",
            type_="foreignkey",
        )
        batch_op.drop_column("storage_policy_decision_id")
        batch_op.drop_column("retrieval_policy_decision_id")
    if dialect == "sqlite":
        op.execute(_SQLITE_UPDATE_TRIGGER)
        op.execute(_SQLITE_DELETE_TRIGGER)
