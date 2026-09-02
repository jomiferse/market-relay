"""Observations v1 endpoints applying the publication policy gate.

tasks.md 5.3; specs/market-observations/spec.md; specs/consumer-api/spec.md.
"""

from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient
from freezegun import freeze_time
from sqlalchemy.orm import Session

from market_relay.domain.governance.models import PolicyCapability
from tests.factories import (
    approve_publication,
    create_equity_listing,
    create_fund_listing,
    deny_capability,
    record_observation,
)


def _auth(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"}


# 2026-01-05 is a Monday (business day), 2026-01-03 is a Saturday, 2026-01-02
# is a Friday: fixed dates so we do not depend on the system clock.
_MONDAY = date(2026, 1, 5)
_SATURDAY = date(2026, 1, 3)
_FRIDAY = date(2026, 1, 2)


def test_latest_observation_returns_close_with_full_provenance(
    api_client: TestClient, db_session: Session, holdria_api_key: str
) -> None:
    listing = create_equity_listing(db_session)
    approve_publication(db_session, "fake", attribute=True)
    record_observation(db_session, listing, session_date=_MONDAY, close="101.50")

    with freeze_time(_MONDAY):
        response = api_client.get(
            f"/v1/listings/{listing.id}/observations/latest", headers=_auth(holdria_api_key)
        )

    assert response.status_code == 200
    body = response.json()
    assert body["availability"] == "OK"
    assert body["session_date"] == _MONDAY.isoformat()
    value = body["value"]
    assert value["close"] == "101.50000000"
    assert value["currency"] == "EUR"
    assert value["source"] == "fake"
    assert value["is_eod"] is True
    assert value["observation_type"] == "EOD_CLOSE"
    assert value["requires_attribution"] is True
    assert value["attribution"] == "Source: fake."
    assert value["revision"] == 1


def test_latest_observation_never_asserts_real_time_pricing(
    api_client: TestClient, db_session: Session, holdria_api_key: str
) -> None:
    """specs/consumer-api/spec.md § 'EOD price request': the response
    identifies its effective date and EOD nature, not a real-time price.
    """

    listing = create_equity_listing(db_session)
    approve_publication(db_session, "fake")
    record_observation(db_session, listing, session_date=_MONDAY)

    with freeze_time(_MONDAY):
        response = api_client.get(
            f"/v1/listings/{listing.id}/observations/latest", headers=_auth(holdria_api_key)
        )

    assert response.json()["value"]["is_eod"] is True


def test_stored_observation_without_redistribute_is_never_returned(
    api_client: TestClient, db_session: Session, holdria_api_key: str
) -> None:
    """specs/consumer-api/spec.md § 'Stored data not redistributable'."""

    listing = create_equity_listing(db_session)
    approve_publication(db_session, "fake")
    deny_capability(db_session, "fake", PolicyCapability.REDISTRIBUTE)
    record_observation(db_session, listing, session_date=_MONDAY, close="999.99")

    with freeze_time(_MONDAY):
        response = api_client.get(
            f"/v1/listings/{listing.id}/observations/latest", headers=_auth(holdria_api_key)
        )

    assert response.status_code == 200
    body = response.json()
    assert body["availability"] == "UNAVAILABLE"
    assert body["value"] is None
    assert "999.99" not in response.text


def test_policy_revocation_removes_previously_publishable_observation(
    api_client: TestClient, db_session: Session, holdria_api_key: str
) -> None:
    """specs/market-observations/spec.md § 'Revoked source': the history
    remains auditable but no longer appears in ordinary responses, without
    mutating any `Observation` row.
    """

    listing = create_equity_listing(db_session)
    approve_publication(db_session, "fake")
    record_observation(db_session, listing, session_date=_MONDAY, close="42.00")

    with freeze_time(_MONDAY):
        before = api_client.get(
            f"/v1/listings/{listing.id}/observations/latest", headers=_auth(holdria_api_key)
        )
    assert before.json()["availability"] == "OK"
    assert before.json()["value"]["close"] == "42.00000000"

    deny_capability(db_session, "fake", PolicyCapability.REDISTRIBUTE)

    with freeze_time(_MONDAY):
        after = api_client.get(
            f"/v1/listings/{listing.id}/observations/latest", headers=_auth(holdria_api_key)
        )
    assert after.json()["availability"] == "UNAVAILABLE"
    assert after.json()["value"] is None


def test_range_distinguishes_no_session_from_unavailable_pending_data(
    api_client: TestClient, db_session: Session, holdria_api_key: str
) -> None:
    """specs/consumer-api/spec.md § 'Range with non-business days'."""

    listing = create_equity_listing(db_session)
    approve_publication(db_session, "fake")
    record_observation(db_session, listing, session_date=_MONDAY, close="10.00")

    response = api_client.get(
        f"/v1/listings/{listing.id}/observations",
        params={"start": _SATURDAY.isoformat(), "end": _MONDAY.isoformat()},
        headers=_auth(holdria_api_key),
    )

    assert response.status_code == 200
    observations = {row["session_date"]: row for row in response.json()["observations"]}
    assert observations[_SATURDAY.isoformat()]["availability"] == "NO_SESSION"
    # Sunday 2026-01-04, between Saturday and Monday, with no observation recorded.
    assert observations["2026-01-04"]["availability"] == "NO_SESSION"
    assert observations[_MONDAY.isoformat()]["availability"] == "OK"
    assert observations[_MONDAY.isoformat()]["value"]["close"] == "10.00000000"


def test_range_marks_expected_session_without_data_as_unavailable(
    api_client: TestClient, db_session: Session, holdria_api_key: str
) -> None:
    listing = create_equity_listing(db_session)
    approve_publication(db_session, "fake")
    # No observation recorded for Monday: expected session but with no
    # publishable data yet.

    response = api_client.get(
        f"/v1/listings/{listing.id}/observations",
        params={"start": _MONDAY.isoformat(), "end": _MONDAY.isoformat()},
        headers=_auth(holdria_api_key),
    )

    body = response.json()["observations"][0]
    assert body["availability"] == "UNAVAILABLE"
    assert body["value"] is None


def test_fund_nav_still_in_publication_window_reports_waiting_state(
    api_client: TestClient, db_session: Session, holdria_api_key: str
) -> None:
    """The fake simulates that Friday's NAV is within the publication
    window (adapters/fake/provider.py), exercising
    `WAITING_FOR_PUBLICATION` (specs/market-data-ingestion/spec.md).
    """

    listing = create_fund_listing(db_session)
    approve_publication(db_session, "fake")

    response = api_client.get(
        f"/v1/listings/{listing.id}/observations",
        params={"start": _FRIDAY.isoformat(), "end": _FRIDAY.isoformat()},
        headers=_auth(holdria_api_key),
    )

    body = response.json()["observations"][0]
    assert body["availability"] == "WAITING_FOR_PUBLICATION"
    assert body["value"] is None


def test_range_rejects_end_before_start(
    api_client: TestClient, db_session: Session, holdria_api_key: str
) -> None:
    listing = create_equity_listing(db_session)

    response = api_client.get(
        f"/v1/listings/{listing.id}/observations",
        params={"start": _MONDAY.isoformat(), "end": _SATURDAY.isoformat()},
        headers=_auth(holdria_api_key),
    )

    assert response.status_code == 422


def test_observations_endpoint_requires_observations_scope(
    api_client: TestClient, db_session: Session, catalog_only_api_key: str
) -> None:
    listing = create_equity_listing(db_session)

    response = api_client.get(
        f"/v1/listings/{listing.id}/observations/latest", headers=_auth(catalog_only_api_key)
    )

    assert response.status_code == 403
