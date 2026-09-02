"""Raw response validation and cursor serialization (tasks.md 4.4, 4.5)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from market_relay.domain.ingestion import FetchCursor, InvalidCursorError, validate_raw_observation
from market_relay.domain.ingestion.validation import MalformedObservationError
from market_relay.domain.observations.models import ObservationType
from market_relay.ports.historical import RawObservation


def _raw(**overrides: object) -> RawObservation:
    base = {
        "external_listing_id": "FAKE-DE0007164600-XETR",
        "session_date": date(2026, 1, 5),
        "observation_type": ObservationType.EOD_CLOSE,
        "currency": "EUR",
        "close": Decimal("100.00"),
    }
    base.update(overrides)
    return RawObservation(**base)  # type: ignore[arg-type]


def test_valid_observation_passes() -> None:
    validate_raw_observation(
        _raw(),
        expected_external_listing_id="FAKE-DE0007164600-XETR",
        expected_start=date(2026, 1, 5),
        expected_end=date(2026, 1, 5),
    )


def test_rejects_mismatched_external_listing_id() -> None:
    with pytest.raises(MalformedObservationError):
        validate_raw_observation(
            _raw(external_listing_id="OTHER-ID"),
            expected_external_listing_id="FAKE-DE0007164600-XETR",
            expected_start=date(2026, 1, 5),
            expected_end=date(2026, 1, 5),
        )


def test_rejects_date_outside_requested_range() -> None:
    with pytest.raises(MalformedObservationError):
        validate_raw_observation(
            _raw(session_date=date(2026, 2, 1)),
            expected_external_listing_id="FAKE-DE0007164600-XETR",
            expected_start=date(2026, 1, 5),
            expected_end=date(2026, 1, 5),
        )


def test_rejects_non_iso_currency() -> None:
    with pytest.raises(MalformedObservationError):
        validate_raw_observation(
            _raw(currency="euro"),
            expected_external_listing_id="FAKE-DE0007164600-XETR",
            expected_start=date(2026, 1, 5),
            expected_end=date(2026, 1, 5),
        )


def test_rejects_non_positive_close() -> None:
    with pytest.raises(MalformedObservationError):
        validate_raw_observation(
            _raw(close=Decimal("-1.00")),
            expected_external_listing_id="FAKE-DE0007164600-XETR",
            expected_start=date(2026, 1, 5),
            expected_end=date(2026, 1, 5),
        )


def test_cursor_round_trips_through_serialization() -> None:
    cursor = FetchCursor(
        external_listing_id="FAKE-DE0007164600-XETR",
        credential_scope="default",
        observation_type=ObservationType.EOD_CLOSE,
        start=date(2026, 1, 5),
        end=date(2026, 1, 9),
    )

    parsed = FetchCursor.parse(cursor.serialize())

    assert parsed == cursor


def test_cursor_parse_rejects_missing_or_malformed_payload() -> None:
    with pytest.raises(InvalidCursorError):
        FetchCursor.parse(None)
    with pytest.raises(InvalidCursorError):
        FetchCursor.parse("not-json")
    with pytest.raises(InvalidCursorError):
        FetchCursor.parse('{"external_listing_id": "x"}')
