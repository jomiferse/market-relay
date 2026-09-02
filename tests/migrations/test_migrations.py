"""Round trip of migrations over an empty database (tasks.md 1.3)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import MetaData, Table, create_engine, insert, inspect, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

EXPECTED_TABLES = {
    "instruments",
    "listings",
    "external_identities",
    "source_policy_decisions",
    "observations",
    "jobs",
}


def test_upgrade_creates_all_expected_tables(alembic_config: Config, sqlite_url: str) -> None:
    command.upgrade(alembic_config, "head")

    engine = create_engine(sqlite_url)
    try:
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
    finally:
        engine.dispose()

    assert EXPECTED_TABLES.issubset(tables)


def test_downgrade_to_base_removes_all_tables(alembic_config: Config, sqlite_url: str) -> None:
    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, "base")

    engine = create_engine(sqlite_url)
    try:
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
    finally:
        engine.dispose()

    assert EXPECTED_TABLES.isdisjoint(tables)
    # `alembic_version` is the only bookkeeping table that Alembic
    # keeps after a full downgrade to `base`.
    assert tables <= {"alembic_version"}


def test_upgrade_downgrade_upgrade_round_trip_is_idempotent(
    alembic_config: Config, sqlite_url: str
) -> None:
    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, "base")
    command.upgrade(alembic_config, "head")

    engine = create_engine(sqlite_url)
    try:
        with engine.connect() as connection:
            context = MigrationContext.configure(connection)
            current_heads = set(context.get_current_heads())
    finally:
        engine.dispose()

    script_dir = ScriptDirectory.from_config(alembic_config)
    assert current_heads == set(script_dir.get_heads())


def test_migration_0002_backfills_dedupe_key_for_preexisting_jobs(
    alembic_config: Config, sqlite_url: str
) -> None:
    """`0002` adds `jobs.dedupe_key` with a shared `server_default` and
    creates a unique constraint on that column; on a database with several
    `jobs` already inserted by `0001`, applying it without backfill would
    make all those rows share the same default value and the unique
    constraint would fail. This test seeds several preexisting `jobs` in
    `0001` and verifies that upgrading to `head` does not fail and that
    each row receives a deterministic, unique `dedupe_key`.
    """

    command.upgrade(alembic_config, "0001")

    engine = create_engine(sqlite_url)
    try:
        metadata = MetaData()
        jobs = Table("jobs", metadata, autoload_with=engine)
        now = datetime(2026, 1, 1, tzinfo=UTC)
        seeded_ids = [str(uuid.uuid4()) for _ in range(5)]
        with engine.begin() as connection:
            for job_id in seeded_ids:
                connection.execute(
                    insert(jobs).values(
                        id=job_id,
                        job_type="fetch_range",
                        source="fake",
                        status="PENDING",
                        attempt_count=0,
                        max_attempts=5,
                        next_run_at=now,
                        generation=0,
                        created_at=now,
                        updated_at=now,
                    )
                )
    finally:
        engine.dispose()

    # SHALL NOT raise IntegrityError from the unique constraint sharing
    # the default value among the preexisting rows.
    command.upgrade(alembic_config, "head")

    engine = create_engine(sqlite_url)
    try:
        metadata = MetaData()
        jobs = Table("jobs", metadata, autoload_with=engine)
        with engine.connect() as connection:
            rows = list(connection.execute(select(jobs.c.id, jobs.c.dedupe_key)))
    finally:
        engine.dispose()

    assert {row.id for row in rows} == set(seeded_ids)
    keys = [row.dedupe_key for row in rows]
    assert all(key for key in keys)  # none was left empty
    assert len(set(keys)) == len(keys)  # all unique, the constraint holds

    # The unique constraint is really still in effect: an explicit
    # duplicate fails.
    engine = create_engine(sqlite_url)
    try:
        metadata = MetaData()
        jobs = Table("jobs", metadata, autoload_with=engine)
        now = datetime(2026, 1, 1, tzinfo=UTC)
        with engine.connect() as connection, connection.begin(), pytest.raises(IntegrityError):
            connection.execute(
                insert(jobs).values(
                    id=str(uuid.uuid4()),
                    job_type="fetch_range",
                    source="fake",
                    dedupe_key=keys[0],
                    status="PENDING",
                    attempt_count=0,
                    max_attempts=5,
                    next_run_at=now,
                    generation=0,
                    created_at=now,
                    updated_at=now,
                )
            )
    finally:
        engine.dispose()


def test_migration_0002_downgrade_upgrade_round_trip_with_preexisting_jobs(
    alembic_config: Config, sqlite_url: str
) -> None:
    command.upgrade(alembic_config, "0001")
    engine = create_engine(sqlite_url)
    try:
        metadata = MetaData()
        jobs = Table("jobs", metadata, autoload_with=engine)
        now = datetime(2026, 1, 1, tzinfo=UTC)
        with engine.begin() as connection:
            for _ in range(3):
                connection.execute(
                    insert(jobs).values(
                        id=str(uuid.uuid4()),
                        job_type="fetch_range",
                        source="fake",
                        status="PENDING",
                        attempt_count=0,
                        max_attempts=5,
                        next_run_at=now,
                        generation=0,
                        created_at=now,
                        updated_at=now,
                    )
                )
    finally:
        engine.dispose()

    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, "0001")
    command.upgrade(alembic_config, "head")

    engine = create_engine(sqlite_url)
    try:
        metadata = MetaData()
        jobs = Table("jobs", metadata, autoload_with=engine)
        with engine.connect() as connection:
            keys = [row[0] for row in connection.execute(select(jobs.c.dedupe_key))]
    finally:
        engine.dispose()

    assert len(keys) == 3
    assert len(set(keys)) == 3


def test_observations_update_and_delete_are_rejected_after_migration_0003(
    alembic_config: Config, sqlite_url: str
) -> None:
    """The `0003` append-only trigger blocks `UPDATE`/`DELETE` on
    `observations` even with raw SQL outside the ORM, and an `INSERT` of a
    new revision is not affected.
    """

    command.upgrade(alembic_config, "head")

    engine = create_engine(sqlite_url)
    try:
        metadata = MetaData()
        listings_meta = Table("listings", metadata, autoload_with=engine)
        instruments_meta = Table("instruments", metadata, autoload_with=engine)
        observations_meta = Table("observations", metadata, autoload_with=engine)
        now = datetime(2026, 1, 1, tzinfo=UTC)
        instrument_id = str(uuid.uuid4())
        listing_id = str(uuid.uuid4())
        observation_id = str(uuid.uuid4())
        with engine.begin() as connection:
            connection.execute(
                insert(instruments_meta).values(
                    id=instrument_id,
                    asset_class="EQUITY",
                    name="SAP SE",
                    isin="DE0007164600",
                    created_at=now,
                    updated_at=now,
                )
            )
            connection.execute(
                insert(listings_meta).values(
                    id=listing_id,
                    instrument_id=instrument_id,
                    mic="XETR",
                    venue="XETR",
                    ticker="SAP",
                    currency="EUR",
                    created_at=now,
                    updated_at=now,
                )
            )
            connection.execute(
                insert(observations_meta).values(
                    id=observation_id,
                    listing_id=listing_id,
                    source="fake",
                    credential_scope="default",
                    external_listing_id="FAKE-DE0007164600-XETR",
                    session_date=now.date(),
                    observation_type="EOD_CLOSE",
                    revision=1,
                    currency="EUR",
                    close="120.50",
                    quality_status="OK",
                    retrieved_at=now,
                    created_at=now,
                )
            )
            # A new revision (INSERT) is never blocked by the
            # trigger: only UPDATE/DELETE are.
            connection.execute(
                insert(observations_meta).values(
                    id=str(uuid.uuid4()),
                    listing_id=listing_id,
                    source="fake",
                    credential_scope="default",
                    external_listing_id="FAKE-DE0007164600-XETR",
                    session_date=now.date(),
                    observation_type="EOD_CLOSE",
                    revision=2,
                    currency="EUR",
                    close="121.00",
                    quality_status="OK",
                    retrieved_at=now,
                    created_at=now,
                )
            )

        with engine.begin() as connection, pytest.raises(DBAPIError):
            connection.execute(
                text("UPDATE observations SET close = '1.00' WHERE id = :id"),
                {"id": str(observation_id)},
            )

        with engine.begin() as connection, pytest.raises(DBAPIError):
            connection.execute(
                text("DELETE FROM observations WHERE id = :id"), {"id": str(observation_id)}
            )

        with engine.connect() as connection:
            rows = list(
                connection.execute(select(observations_meta.c.close, observations_meta.c.revision))
            )
    finally:
        engine.dispose()

    assert len(rows) == 2
    assert {float(row.close) for row in rows} == {120.50, 121.00}


def test_no_schema_drift_between_models_and_migrations(migrated_engine) -> None:
    """The migrated database exactly reflects `Base.metadata` (with no
    pending autogenerate), preventing the ORM and migrations from
    silently diverging.
    """

    from alembic.autogenerate import compare_metadata

    from market_relay.db import Base

    with migrated_engine.connect() as connection:
        context = MigrationContext.configure(connection)
        diff = compare_metadata(context, Base.metadata)

    assert diff == []
