"""Validated configuration for the service.

The configuration never retains secret values. When a source needs
credentials, `Settings` only stores an opaque identifier (e.g. the name of
an environment variable) that the adapter resolves at the last moment via
`market_relay.domain.governance.credentials`. See `design.md` § "Stack,
persistence and deployment" and § "Isolated central credentials".
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache

from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    """Runtime environment of the service."""

    LOCAL = "local"
    TEST = "test"
    PRODUCTION = "production"


class ConsumerCredentialConfig(BaseModel):
    """Opaque reference to an API consumer's credential (5.2).

    Never contains the secret: `env_var` is, just like for price sources
    (`domain.governance.credentials.CredentialReference`), the name of the
    environment variable that the central resolver reads right before
    comparing the presented credential (`domain.governance.consumer_auth`).
    `scopes` bounds which operations that credential authorizes:
    authentication alone is not enough to authorize a specific operation.
    """

    consumer_id: str
    env_var: str
    scopes: tuple[str, ...] = ()


class Settings(BaseSettings):
    """Configuration validated at startup, with no external credentials required.

    The service SHALL start without any external provider credential: the
    only adapter active by default is the deterministic `fake` provider
    (see `specs/source-governance/spec.md` § "Safe test adapters").
    """

    model_config = SettingsConfigDict(
        env_prefix="MARKET_RELAY_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: Environment = Environment.LOCAL
    service_name: str = "market-relay"

    # SQLite is the default path for local development and reproducible
    # tests; PostgreSQL is the deployment engine (design.md).
    database_url: str = "sqlite:///./market_relay.db"

    # Explicitly enabled price sources. No external source is activated by
    # default; only the deterministic fake provider is safe without
    # APPROVED policy evidence (specs/source-governance/spec.md).
    enabled_sources: tuple[str, ...] = ("fake",)

    # Bounded number of jobs processed per run of the single scheduler
    # (specs/operations/spec.md § "Portable scheduled entry point").
    scheduler_batch_size: int = Field(default=50, gt=0, le=1000)

    # Claims expire so a crashed process cannot strand work. The generation
    # counter fences a former owner after recovery.
    job_lease_seconds: int = Field(default=300, gt=0, le=86400)

    # Delay before a not-yet-published observation is reconsidered.
    waiting_publication_retry_seconds: int = Field(default=3600, gt=0, le=86400)

    # Hard wall-clock limit for isolated provider execution.
    provider_timeout_seconds: float = Field(default=30.0, gt=0, le=300)

    # Threshold in seconds beyond which a pending job is considered
    # stalled for observability purposes.
    stalled_job_threshold_seconds: int = Field(default=3600, gt=0)

    # Authorized consumers of the versioned read API (tasks.md
    # 5.2). Holdria is the only consumer planned for the MVP
    # (design.md § "Internal read API"); the list stays open to more
    # entries without changing the contract. No entry contains a secret:
    # the real value is resolved from `env_var` at authentication time.
    # Holdria never receives the `operations:metrics` scope: the tasks.md
    # 6.2 metrics include the internal source name per job (an adapter
    # identifier, never a credential) and are reserved for a separate
    # operational consumer, so that `/status/operations` — the only
    # endpoint Holdria sees — keeps not revealing which concrete source
    # backs each data point (tests/integration/test_api_status.py).
    consumer_credentials: tuple[ConsumerCredentialConfig, ...] = (
        ConsumerCredentialConfig(
            consumer_id="holdria",
            env_var="MARKET_RELAY_CONSUMER_HOLDRIA_API_KEY",
            scopes=("catalog:read", "observations:read", "operations:read"),
        ),
        ConsumerCredentialConfig(
            consumer_id="ops",
            env_var="MARKET_RELAY_CONSUMER_OPS_API_KEY",
            scopes=("operations:metrics",),
        ),
    )

    @field_validator("database_url")
    @classmethod
    def _validate_database_url(cls, value: str) -> str:
        if not value.startswith(("sqlite://", "postgresql://", "postgresql+psycopg://")):
            raise ValueError(
                "database_url must use the sqlite:// or postgresql(+psycopg):// dialect"
            )
        return value

    @field_validator("enabled_sources")
    @classmethod
    def _validate_enabled_sources(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if "fake" not in value and len(value) == 0:
            raise ValueError("enabled_sources cannot be empty")
        return value

    @model_validator(mode="after")
    def _validate_provider_deadline_within_lease(self) -> Settings:
        if self.provider_timeout_seconds >= self.job_lease_seconds:
            raise ValueError("provider_timeout_seconds must be shorter than job_lease_seconds")
        return self

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite://")


@lru_cache
def get_settings() -> Settings:
    """Builds and validates the configuration once per process."""

    return Settings()
