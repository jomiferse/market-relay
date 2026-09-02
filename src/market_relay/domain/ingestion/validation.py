"""Schema validation of raw responses before persisting them.

`specs/market-data-ingestion/spec.md` § "Malformed response" requires that a
response that fails schema, identifier, or currency validation be rejected
in isolation, recording a sanitized failure and letting the rest of the
jobs continue — never aborting the whole batch over one invalid row.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

from market_relay.ports.historical import RawObservation

_CURRENCY_PATTERN = re.compile(r"^[A-Z]{3}$")


class MalformedObservationError(Exception):
    """A raw observation fails schema/currency/id validation.

    The message never includes the full raw value of a field that could
    carry sensitive provider data; only the field name and the reason.
    """


def validate_raw_observation(
    raw: RawObservation,
    *,
    expected_external_listing_id: str,
    expected_start: date,
    expected_end: date,
) -> None:
    """Raises `MalformedObservationError` if `raw` is not usable.

    Checks the identifier, the requested date window, a three-letter
    ISO-4217 currency, and that `close` is a finite, positive `Decimal`.
    Does not repair nor normalize the value: only accepts or rejects.
    """

    if raw.external_listing_id != expected_external_listing_id:
        raise MalformedObservationError("external_listing_id does not match the requested one.")
    if not (expected_start <= raw.session_date <= expected_end):
        raise MalformedObservationError("session_date is outside the requested range.")
    if not isinstance(raw.currency, str) or not _CURRENCY_PATTERN.match(raw.currency):
        raise MalformedObservationError("currency is not a 3-letter ISO-4217 code.")
    if not isinstance(raw.close, Decimal) or raw.close <= 0 or not raw.close.is_finite():
        raise MalformedObservationError("close is not a positive, finite decimal value.")
