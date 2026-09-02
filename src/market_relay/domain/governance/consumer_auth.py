"""Authentication and authorization of API consumers (tasks.md 5.2).

`specs/consumer-api/spec.md` § "Versioned and authenticated API" requires
that every non-public operation require an authorized consumer identity and
that a rejection reveal no data, configuration, or existence of secrets.
`specs/source-governance/spec.md` § "Credential protection" applies equally
to consumer credentials: they live only on the server, are resolved right
before comparison, and no log, error, or response includes them.

Just like `domain.governance.credentials` for external sources, the
identity of a consumer (e.g. Holdria) is referenced through an opaque
identifier (`env_var`), never the secret itself; the real value is only
read from the environment at the instant the presented credential is
compared, and the comparison uses `hmac.compare_digest` to avoid leaking the
secret via timing.
"""

from __future__ import annotations

import hmac
from dataclasses import dataclass

from market_relay.domain.governance.credentials import (
    CredentialNotFoundError,
    CredentialReference,
    CredentialResolver,
)


class ConsumerAuthenticationError(Exception):
    """Missing or invalid consumer credential.

    The message never identifies which consumer was attempted to
    authenticate, nor whether the problem was missing configuration or an
    incorrect value: every failure variant collapses to the same
    non-sensitive error (specs/consumer-api/spec.md § "Unauthenticated
    consumer").
    """


class ConsumerAuthorizationError(Exception):
    """Consumer authenticated but without the scope required for the operation.

    `consumer_id` and `required_scope` are not secrets (they are public
    configuration identifiers, not credentials), so the message can include
    them without violating "Credential protection"; even so, the HTTP
    handler that translates this exception SHALL return a generic detail to
    the client, never this internal message.
    """

    def __init__(self, consumer_id: str, required_scope: str) -> None:
        self.consumer_id = consumer_id
        self.required_scope = required_scope
        super().__init__(f"Consumer '{consumer_id}' lacks scope '{required_scope}'.")


@dataclass(frozen=True, slots=True)
class ConsumerCredential:
    """Opaque reference to an API consumer's credential.

    Never contains the secret: `env_var` is, in development, the name of
    the environment variable that holds it; in a deployment with a
    dedicated secrets manager the same field would be reused as the
    identifier for that manager without changing this contract (design.md §
    "Isolated central credentials").
    """

    consumer_id: str
    env_var: str
    scopes: tuple[str, ...]

    def credential_reference(self) -> CredentialReference:
        return CredentialReference(
            source=f"consumer:{self.consumer_id}",
            credential_scope="api-key",
            env_var=self.env_var,
        )


@dataclass(frozen=True, slots=True)
class ConsumerIdentity:
    """Resolved identity of an authenticated consumer."""

    consumer_id: str
    scopes: tuple[str, ...]

    def has_scope(self, scope: str) -> bool:
        return scope in self.scopes


class ConsumerAuthenticator:
    """Resolves opaque credentials and authenticates/authorizes consumers.

    Checks the presented key against *all* registered credentials, without
    short-circuiting on the first match, so as not to leak via timing how
    many credentials are configured or which of them (if any) matched.
    """

    def __init__(
        self,
        credentials: tuple[ConsumerCredential, ...],
        resolver: CredentialResolver | None = None,
    ) -> None:
        self._credentials = credentials
        self._resolver = resolver or CredentialResolver()

    def authenticate(self, presented_api_key: str | None) -> ConsumerIdentity:
        if not presented_api_key:
            raise ConsumerAuthenticationError("Missing consumer credential.")

        matched: ConsumerIdentity | None = None
        for credential in self._credentials:
            try:
                configured = self._resolver.resolve(credential.credential_reference())
            except CredentialNotFoundError:
                # A credential that is configured but has no value in the
                # current environment is never distinguished, from the
                # consumer's perspective, from a credential that simply
                # does not match.
                continue
            if hmac.compare_digest(configured.get_secret_value(), presented_api_key):
                matched = ConsumerIdentity(
                    consumer_id=credential.consumer_id, scopes=credential.scopes
                )

        if matched is None:
            raise ConsumerAuthenticationError("Invalid consumer credential.")
        return matched

    @staticmethod
    def authorize(identity: ConsumerIdentity, required_scope: str) -> None:
        if not identity.has_scope(required_scope):
            raise ConsumerAuthorizationError(identity.consumer_id, required_scope)
