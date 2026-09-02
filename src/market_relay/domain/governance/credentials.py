"""Opaque credential resolution and message sanitization.

`specs/source-governance/spec.md` § "Credential protection" requires that
secrets remain exclusively on the server, are never returned in plain text,
and never appear in logs, metrics, fixtures, errors, or responses.
`design.md` § "Isolated central credentials" adds that configuration only
holds opaque identifiers and that adapters resolve the real value from the
environment's secrets manager right before using it — environment variables
only for development.

This module never persists a secret value: not in the database, not in
attributes readable via `repr()`/`str()`, and not in exceptions.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

from pydantic import SecretStr


class CredentialNotFoundError(Exception):
    """The opaque reference does not resolve to any value in the current environment.

    The message only includes the opaque identifier (environment variable
    name or scope), never a secret value.
    """


@dataclass(frozen=True, slots=True)
class CredentialReference:
    """Opaque locator of a credential: never contains the secret.

    `env_var` is, in development, the name of the environment variable that
    holds the value; in a deployment with a dedicated secrets manager this
    same field would be reused as the identifier for that manager without
    changing the domain contract.
    """

    source: str
    credential_scope: str
    env_var: str


class CredentialResolver:
    """Resolves a `CredentialReference` to its value right before using it.

    Does not cache the value in a visible instance attribute nor log it
    anywhere: each call rereads the environment and returns a `SecretStr`,
    whose default Pydantic `repr()`/`str()` already masks it.
    """

    def resolve(self, reference: CredentialReference) -> SecretStr:
        raw_value = os.environ.get(reference.env_var)
        if not raw_value:
            raise CredentialNotFoundError(
                f"No value for opaque reference '{reference.env_var}' "
                f"(source='{reference.source}', scope='{reference.credential_scope}')."
            )
        return SecretStr(raw_value)


# Common secret patterns embedded in URLs or provider error messages, used
# to sanitize before logging (specs/source-governance § "Provider
# authentication error": never include the secret nor the full URL if it
# contains one).
_URL_CREDENTIAL_PATTERN = re.compile(r"(://)([^/@\s]+)(@)")
_QUERY_SECRET_PATTERN = re.compile(
    r"((?:api[_-]?key|token|secret|password|apikey)=)([^&\s]+)", re.IGNORECASE
)


def sanitize_message(message: str, *, known_secrets: tuple[str, ...] = ()) -> str:
    """Redacts credentials from a message before logging or exposing it.

    Covers three cases: credentials embedded in a URL's authority
    (`https://user:pass@host`), sensitive query parameters (`?api_key=...`),
    and, as a last resort, any known secret value explicitly passed in
    `known_secrets`.
    """

    sanitized = _URL_CREDENTIAL_PATTERN.sub(r"\1***\3", message)
    sanitized = _QUERY_SECRET_PATTERN.sub(r"\1***", sanitized)
    for secret in known_secrets:
        if secret:
            sanitized = sanitized.replace(secret, "***")
    return sanitized
