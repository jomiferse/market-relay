"""Common fixtures: Alembic-migrated SQLite test database, and the FastAPI
app with test consumers for the API's contract, integration and security
tests (tasks.md 5.1-5.4).
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from market_relay.api.app import create_app
from market_relay.api.deps import get_db
from market_relay.config import ConsumerCredentialConfig, Settings
from market_relay.db.session import build_session_factory, create_engine_from_settings

REPO_ROOT = Path(__file__).resolve().parents[1]

# Deterministic test decoys: never real credentials
# (tests/security/test_credentials.py follows the same convention).
HOLDRIA_API_KEY_ENV = "MARKET_RELAY_CONSUMER_HOLDRIA_API_KEY"
HOLDRIA_DECOY_API_KEY = "decoy-holdria-api-key-not-real"  # nosec
CATALOG_ONLY_API_KEY_ENV = "MARKET_RELAY_CONSUMER_CATALOG_ONLY_API_KEY"
CATALOG_ONLY_DECOY_API_KEY = "decoy-catalog-only-api-key-not-real"  # nosec
OPS_API_KEY_ENV = "MARKET_RELAY_CONSUMER_OPS_API_KEY"
OPS_DECOY_API_KEY = "decoy-ops-api-key-not-real"  # nosec


@pytest.fixture
def sqlite_url(tmp_path: Path) -> str:
    db_path = tmp_path / "market_relay_test.db"
    return f"sqlite:///{db_path}"


@pytest.fixture
def alembic_config(sqlite_url: str) -> Config:
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", sqlite_url)
    return config


@pytest.fixture
def migrated_engine(alembic_config: Config, sqlite_url: str) -> Iterator[Engine]:
    command.upgrade(alembic_config, "head")
    settings = Settings(database_url=sqlite_url)
    engine = create_engine_from_settings(settings)
    yield engine
    engine.dispose()


@pytest.fixture
def session_factory(migrated_engine: Engine) -> sessionmaker[Session]:
    return build_session_factory(migrated_engine)


@pytest.fixture
def db_session(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def holdria_api_key(monkeypatch: pytest.MonkeyPatch) -> str:
    """Consumer with all scopes (represents Holdria in production)."""

    monkeypatch.setenv(HOLDRIA_API_KEY_ENV, HOLDRIA_DECOY_API_KEY)
    return HOLDRIA_DECOY_API_KEY


@pytest.fixture
def catalog_only_api_key(monkeypatch: pytest.MonkeyPatch) -> str:
    """Consumer with an insufficient scope, to test denied access."""

    monkeypatch.setenv(CATALOG_ONLY_API_KEY_ENV, CATALOG_ONLY_DECOY_API_KEY)
    return CATALOG_ONLY_DECOY_API_KEY


@pytest.fixture
def ops_api_key(monkeypatch: pytest.MonkeyPatch) -> str:
    """Operational consumer holding the `operations:metrics` scope
    (tasks.md 6.2), never granted to Holdria.
    """

    monkeypatch.setenv(OPS_API_KEY_ENV, OPS_DECOY_API_KEY)
    return OPS_DECOY_API_KEY


@pytest.fixture
def api_settings(sqlite_url: str) -> Settings:
    return Settings(
        database_url=sqlite_url,
        consumer_credentials=(
            ConsumerCredentialConfig(
                consumer_id="holdria",
                env_var=HOLDRIA_API_KEY_ENV,
                scopes=("catalog:read", "observations:read", "operations:read"),
            ),
            ConsumerCredentialConfig(
                consumer_id="catalog-only-consumer",
                env_var=CATALOG_ONLY_API_KEY_ENV,
                scopes=("catalog:read",),
            ),
            ConsumerCredentialConfig(
                consumer_id="ops",
                env_var=OPS_API_KEY_ENV,
                scopes=("operations:metrics",),
            ),
        ),
    )


@pytest.fixture
def api_client(api_settings: Settings, db_session: Session) -> Iterator[TestClient]:
    """`TestClient` with the migrated database from `db_session` injected.

    Authentication uses the real `ConsumerAuthenticator` built from
    `api_settings`: the tests exercise the full authentication flow,
    not a mocked stand-in.
    """

    app = create_app(settings=api_settings)

    def _override_get_db() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as client:
        yield client
