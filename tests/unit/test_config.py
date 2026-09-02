"""Validated configuration and startup without external credentials (tasks.md 1.2)."""

from __future__ import annotations

import os

import pytest
from pydantic import ValidationError

from market_relay.config.settings import Environment, Settings


def test_settings_default_to_sqlite_and_fake_source_only() -> None:
    settings = Settings(_env_file=None)

    assert settings.is_sqlite
    assert settings.enabled_sources == ("fake",)
    assert settings.environment is Environment.LOCAL


def test_settings_load_without_any_external_credential(monkeypatch: pytest.MonkeyPatch) -> None:
    """The service SHALL start with no external provider credential."""

    for key in list(os.environ):
        if key.startswith("MARKET_RELAY_") and "SOURCE" in key.upper():
            monkeypatch.delenv(key, raising=False)

    settings = Settings(_env_file=None)

    assert settings.enabled_sources == ("fake",)


def test_settings_reject_unsupported_database_dialect() -> None:
    with pytest.raises(ValidationError):
        Settings(database_url="mysql://user@host/db", _env_file=None)


def test_settings_reject_non_positive_batch_size() -> None:
    with pytest.raises(ValidationError):
        Settings(scheduler_batch_size=0, _env_file=None)


def test_get_settings_is_cached() -> None:
    from market_relay.config.settings import get_settings

    get_settings.cache_clear()
    first = get_settings()
    second = get_settings()

    assert first is second
    get_settings.cache_clear()
