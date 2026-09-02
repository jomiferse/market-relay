"""Opaque credential resolution: a decoy secret never appears in
logs, errors, or responses (tasks.md 2.3; specs/source-governance/spec.md
§ 'Credential protection').
"""

from __future__ import annotations

import logging

import pytest

from market_relay.domain.governance.credentials import (
    CredentialNotFoundError,
    CredentialReference,
    CredentialResolver,
    sanitize_message,
)

DECOY_SECRET = "sk_live_DECOY_1234567890abcdef"  # nosec: test decoy value


@pytest.fixture
def decoy_env(monkeypatch: pytest.MonkeyPatch) -> CredentialReference:
    monkeypatch.setenv("MARKET_RELAY_SOURCE_ACME_API_KEY", DECOY_SECRET)
    return CredentialReference(
        source="acme-source",
        credential_scope="default",
        env_var="MARKET_RELAY_SOURCE_ACME_API_KEY",
    )


def test_resolver_returns_secret_str_never_plain_str(decoy_env: CredentialReference) -> None:
    resolver = CredentialResolver()

    resolved = resolver.resolve(decoy_env)

    assert resolved.get_secret_value() == DECOY_SECRET
    # `str()`/`repr()` — what would end up in a log or traceback — never
    # contains the real value.
    assert DECOY_SECRET not in str(resolved)
    assert DECOY_SECRET not in repr(resolved)


def test_missing_credential_error_never_includes_secret_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MARKET_RELAY_SOURCE_MISSING_API_KEY", raising=False)
    reference = CredentialReference(
        source="missing-source",
        credential_scope="default",
        env_var="MARKET_RELAY_SOURCE_MISSING_API_KEY",
    )
    resolver = CredentialResolver()

    with pytest.raises(CredentialNotFoundError) as exc_info:
        resolver.resolve(reference)

    assert DECOY_SECRET not in str(exc_info.value)


def test_sanitize_message_redacts_url_embedded_credential() -> None:
    message = f"error connecting to https://user:{DECOY_SECRET}@api.acme.example/prices"

    sanitized = sanitize_message(message)

    assert DECOY_SECRET not in sanitized
    assert "***" in sanitized


def test_sanitize_message_redacts_query_string_api_key() -> None:
    message = f"GET https://api.acme.example/prices?api_key={DECOY_SECRET}&symbol=SAP failed"

    sanitized = sanitize_message(message)

    assert DECOY_SECRET not in sanitized


def test_sanitize_message_redacts_known_secret_as_last_resort() -> None:
    message = f"provider rejected the credential {DECOY_SECRET}"

    sanitized = sanitize_message(message, known_secrets=(DECOY_SECRET,))

    assert DECOY_SECRET not in sanitized


def test_decoy_secret_never_reaches_log_records(
    decoy_env: CredentialReference, caplog: pytest.LogCaptureFixture
) -> None:
    """Simulates the 'provider authentication error' flow: a sanitized
    error is logged without the secret.
    """

    resolver = CredentialResolver()
    resolved = resolver.resolve(decoy_env)

    with caplog.at_level(logging.ERROR):
        logger = logging.getLogger("market_relay.adapters.acme")
        # A correct adapter never interpolates the revealed value into a
        # log; it only references the opaque locator.
        logger.error(
            sanitize_message(
                f"provider '{decoy_env.source}' rejected the credential for scope "
                f"'{decoy_env.credential_scope}'"
            )
        )

    for record in caplog.records:
        assert DECOY_SECRET not in record.getMessage()
    # The resolution itself worked (the secret remains accessible only
    # through the explicit `get_secret_value()` path, never leaked to logs).
    assert resolved.get_secret_value() == DECOY_SECRET


def test_decoy_secret_never_reaches_an_http_error_response(
    decoy_env: CredentialReference,
) -> None:
    """An adapter that fails while using the credential SHALL expose a
    sanitized HTTP error, never the resolved secret nor the raw opaque
    reference.
    """

    from fastapi import FastAPI, HTTPException
    from fastapi.testclient import TestClient

    resolver = CredentialResolver()
    app = FastAPI()

    @app.get("/adapters/acme/probe")
    def probe() -> None:
        resolved = resolver.resolve(decoy_env)
        # Simulates a provider rejection: the message is sanitized before
        # being included in the error response, the secret is never interpolated.
        message = sanitize_message(
            f"provider '{decoy_env.source}' rejected the credential",
            known_secrets=(resolved.get_secret_value(),),
        )
        raise HTTPException(status_code=502, detail=message)

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/adapters/acme/probe")

    assert DECOY_SECRET not in response.text
