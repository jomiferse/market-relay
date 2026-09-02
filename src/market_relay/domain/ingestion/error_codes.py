"""Bounded, generic error codes for adapter-originated failures.

A provider's exception message is untrusted free text: `sanitize_message`
only redacts the two shapes of embedded credential it knows how to
recognize (a URL authority and a `key=value` query parameter). A secret in
any other shape — a bare token in a plain-text body, a header dump, a stack
trace fragment — passes straight through regex sanitization unredacted.
Metrics and logs SHALL therefore never surface a provider's raw exception
text at all, regardless of whether it was "sanitized" first: the only
values ever exposed for an adapter failure (quota checks, calendar refresh,
historical fetch) come from this closed, finite set of codes, never from
`str(exc)`.
"""

from __future__ import annotations

from market_relay.adapters.registry import UnknownSourceError
from market_relay.domain.ingestion.provider_execution import ProviderTimeoutError

UNKNOWN_SOURCE = "unknown_source"
ADAPTER_ERROR = "adapter_error"
PROVIDER_TIMEOUT = "provider_timeout"


def adapter_error_code(exc: Exception) -> str:
    """Maps an adapter-raised exception to a bounded, generic error code.

    Never inspects or includes any text from `exc` itself. `UnknownSourceError`
    is distinguished because it is raised by our own registry (never by a
    provider) and is useful to an operator diagnosing a misconfiguration;
    every other exception — including anything a real provider adapter might
    raise — collapses to the single generic `ADAPTER_ERROR` code.
    """

    if isinstance(exc, UnknownSourceError):
        return UNKNOWN_SOURCE
    if isinstance(exc, ProviderTimeoutError):
        return PROVIDER_TIMEOUT
    return ADAPTER_ERROR
