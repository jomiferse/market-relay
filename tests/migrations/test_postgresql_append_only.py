"""Maintained PostgreSQL migration and append-only integration check."""

from __future__ import annotations

import shutil
import socket
import subprocess
import time
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from tests.conftest import REPO_ROOT


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture(scope="module")
def postgresql_url() -> Iterator[str]:
    docker = shutil.which("docker")
    if docker is None:
        pytest.skip("Docker is required for the PostgreSQL integration test")
    probe = subprocess.run(  # noqa: S603
        [docker, "info"], capture_output=True, text=True, timeout=10, check=False
    )
    if probe.returncode != 0:
        pytest.skip("Docker daemon is unavailable")

    name = f"market-relay-pg-test-{uuid.uuid4().hex[:10]}"
    port = _free_port()
    subprocess.run(  # noqa: S603
        [
            docker,
            "run",
            "--rm",
            "-d",
            "--name",
            name,
            "-e",
            "POSTGRES_HOST_AUTH_METHOD=trust",
            "-p",
            f"127.0.0.1:{port}:5432",
            "postgres:17-alpine",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    try:
        for _ in range(60):
            ready = subprocess.run(  # noqa: S603
                [docker, "exec", name, "pg_isready", "-U", "postgres"],
                capture_output=True,
                timeout=5,
                check=False,
            )
            if ready.returncode == 0:
                break
            time.sleep(0.25)
        else:
            pytest.fail("Ephemeral PostgreSQL did not become ready")
        yield f"postgresql+psycopg://postgres@127.0.0.1:{port}/postgres"
    finally:
        subprocess.run(  # noqa: S603
            [docker, "rm", "-f", name], capture_output=True, timeout=15, check=False
        )


def test_postgresql_migrations_enforce_observation_append_only(postgresql_url: str) -> None:
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", postgresql_url)
    command.upgrade(config, "head")

    engine = create_engine(postgresql_url)
    now = datetime(2026, 1, 1, tzinfo=UTC)
    instrument_id, listing_id, observation_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    retrieval_policy_id, storage_policy_id = uuid.uuid4(), uuid.uuid4()
    try:
        with engine.begin() as connection:
            for policy_id, capability in (
                (retrieval_policy_id, "RETRIEVE"),
                (storage_policy_id, "STORE"),
            ):
                connection.execute(
                    text(
                        "INSERT INTO source_policy_decisions "
                        "(id, source, capability, version, status, evidence_reference, "
                        "reviewed_by, reviewed_at, created_at) VALUES "
                        "(:id, 'test', :capability, 1, 'APPROVED', 'internal:test-only', "
                        "'test-suite', :now, :now)"
                    ),
                    {"id": policy_id, "capability": capability, "now": now},
                )
            connection.execute(
                text(
                    "INSERT INTO instruments "
                    "(id, asset_class, name, isin, created_at, updated_at) "
                    "VALUES (:id, 'EQUITY', 'PostgreSQL Test', 'DE0000000081', :now, :now)"
                ),
                {"id": instrument_id, "now": now},
            )
            connection.execute(
                text(
                    "INSERT INTO listings "
                    "(id, instrument_id, mic, venue, ticker, currency, created_at, updated_at) "
                    "VALUES (:id, :instrument_id, 'XETR', 'Xetra', 'PGT', 'EUR', :now, :now)"
                ),
                {"id": listing_id, "instrument_id": instrument_id, "now": now},
            )
            connection.execute(
                text(
                    "INSERT INTO observations "
                    "(id, listing_id, source, credential_scope, external_listing_id, "
                    "session_date, observation_type, revision, currency, close, "
                    "quality_status, retrieved_at, retrieval_policy_decision_id, "
                    "storage_policy_decision_id, created_at) VALUES "
                    "(:id, :listing_id, 'test', 'default', 'PG-TEST', :day, "
                    "'EOD_CLOSE', 1, 'EUR', 10, 'OK', :now, :retrieval_policy_id, "
                    ":storage_policy_id, :now)"
                ),
                {
                    "id": observation_id,
                    "listing_id": listing_id,
                    "day": now.date(),
                    "now": now,
                    "retrieval_policy_id": retrieval_policy_id,
                    "storage_policy_id": storage_policy_id,
                },
            )

        for statement in (
            "UPDATE observations SET close=11 WHERE id=:id",
            "DELETE FROM observations WHERE id=:id",
        ):
            with pytest.raises(DBAPIError), engine.begin() as connection:
                connection.execute(text(statement), {"id": observation_id})

        with engine.connect() as connection:
            remaining = connection.scalar(
                text("SELECT count(*) FROM observations WHERE id=:id"), {"id": observation_id}
            )
        assert remaining == 1

        for statement in (
            "UPDATE source_policy_decisions SET status='DENIED' WHERE id=:id",
            "DELETE FROM source_policy_decisions WHERE id=:id",
        ):
            with pytest.raises(DBAPIError), engine.begin() as connection:
                connection.execute(text(statement), {"id": retrieval_policy_id})
        with engine.connect() as connection:
            assert (
                connection.scalar(
                    text("SELECT count(*) FROM source_policy_decisions WHERE id=:id"),
                    {"id": retrieval_policy_id},
                )
                == 1
            )
    finally:
        engine.dispose()
