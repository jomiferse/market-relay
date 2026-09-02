"""API consumer authentication/authorization (tasks.md 5.2;
specs/consumer-api/spec.md § "Unauthenticated consumer").
"""

from __future__ import annotations

import pytest

from market_relay.domain.governance.consumer_auth import (
    ConsumerAuthenticationError,
    ConsumerAuthenticator,
    ConsumerAuthorizationError,
    ConsumerCredential,
)

DECOY_API_KEY = "decoy-consumer-api-key-not-real"  # nosec: test decoy value


@pytest.fixture
def authenticator(monkeypatch: pytest.MonkeyPatch) -> ConsumerAuthenticator:
    monkeypatch.setenv("MARKET_RELAY_CONSUMER_HOLDRIA_API_KEY", DECOY_API_KEY)
    monkeypatch.delenv("MARKET_RELAY_CONSUMER_UNCONFIGURED_API_KEY", raising=False)
    credentials = (
        ConsumerCredential(
            consumer_id="holdria",
            env_var="MARKET_RELAY_CONSUMER_HOLDRIA_API_KEY",
            scopes=("catalog:read", "observations:read"),
        ),
        ConsumerCredential(
            consumer_id="never-configured",
            env_var="MARKET_RELAY_CONSUMER_UNCONFIGURED_API_KEY",
            scopes=("catalog:read",),
        ),
    )
    return ConsumerAuthenticator(credentials)


def test_valid_credential_authenticates_and_authorizes_scope(
    authenticator: ConsumerAuthenticator,
) -> None:
    identity = authenticator.authenticate(DECOY_API_KEY)

    assert identity.consumer_id == "holdria"
    authenticator.authorize(identity, "catalog:read")  # does not raise


def test_authenticated_consumer_without_scope_is_denied(
    authenticator: ConsumerAuthenticator,
) -> None:
    identity = authenticator.authenticate(DECOY_API_KEY)

    with pytest.raises(ConsumerAuthorizationError) as exc_info:
        authenticator.authorize(identity, "operations:read")
    assert exc_info.value.consumer_id == "holdria"
    assert exc_info.value.required_scope == "operations:read"


def test_wrong_api_key_is_rejected_as_invalid(authenticator: ConsumerAuthenticator) -> None:
    with pytest.raises(ConsumerAuthenticationError):
        authenticator.authenticate("not-the-right-key")


def test_missing_api_key_is_rejected(authenticator: ConsumerAuthenticator) -> None:
    with pytest.raises(ConsumerAuthenticationError):
        authenticator.authenticate(None)
    with pytest.raises(ConsumerAuthenticationError):
        authenticator.authenticate("")


def test_credential_never_configured_in_environment_is_never_matched(
    authenticator: ConsumerAuthenticator,
) -> None:
    """A credential registered with no value in the current environment
    (e.g. a disabled consumer) SHALL behave as if it did not exist, never
    raise a distinct error that reveals its presence in the configuration.
    """

    with pytest.raises(ConsumerAuthenticationError):
        authenticator.authenticate("any-arbitrary-value")


def test_authentication_error_never_reveals_which_consumer_or_reason(
    authenticator: ConsumerAuthenticator,
) -> None:
    """specs/consumer-api/spec.md § 'Unauthenticated consumer': the
    rejection reveals no data, configuration, or existence of secrets. We
    verify that the exception message includes no consumer identifier nor
    the presented value.
    """

    with pytest.raises(ConsumerAuthenticationError) as exc_info:
        authenticator.authenticate("wrong-value")

    message = str(exc_info.value)
    assert "holdria" not in message
    assert "never-configured" not in message
    assert DECOY_API_KEY not in message
    assert "wrong-value" not in message
