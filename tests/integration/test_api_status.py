"""Operational status and v1 data endpoints (tasks.md 5.1;
specs/operations/spec.md § 'Minimum observability').
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from market_relay.db.base import utcnow
from market_relay.domain.governance.models import PolicyCapability
from market_relay.domain.observations.models import Job, JobStatus
from tests.factories import (
    approve_publication,
    create_equity_listing,
    deny_capability,
    record_observation,
)


def _auth(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"}


def test_operational_status_reports_no_pending_jobs_when_queue_is_empty(
    api_client: TestClient, holdria_api_key: str
) -> None:
    response = api_client.get("/v1/status/operations", headers=_auth(holdria_api_key))

    assert response.status_code == 200
    body = response.json()
    assert body["pending_jobs"] == 0
    assert body["oldest_pending_seconds"] is None
    assert body["stalled"] is False
    assert body["environment"] == "local"


def test_operational_status_flags_stalled_pending_job(
    api_client: TestClient, db_session: Session, holdria_api_key: str
) -> None:
    db_session.add(
        Job(
            job_type="fetch_range",
            dedupe_key="fake:listing-1:EOD_CLOSE:2020-01-01:2020-01-01",
            source="fake",
            status=JobStatus.PENDING,
            created_at=utcnow() - timedelta(hours=2),
            next_run_at=utcnow(),
        )
    )
    db_session.commit()

    response = api_client.get("/v1/status/operations", headers=_auth(holdria_api_key))

    body = response.json()
    assert body["pending_jobs"] == 1
    assert body["oldest_pending_seconds"] is not None
    assert body["oldest_pending_seconds"] >= 7000
    assert body["stalled"] is True


def test_operational_status_never_includes_job_identifiers_or_source_detail(
    api_client: TestClient, db_session: Session, holdria_api_key: str
) -> None:
    db_session.add(
        Job(
            job_type="fetch_range",
            dedupe_key="acme-secret-source:listing-1:EOD_CLOSE:2020-01-01:2020-01-01",
            source="acme-secret-source",
            status=JobStatus.PENDING,
            next_run_at=utcnow(),
        )
    )
    db_session.commit()

    response = api_client.get("/v1/status/operations", headers=_auth(holdria_api_key))

    assert "acme-secret-source" not in response.text
    assert "fetch_range" not in response.text


def test_scheduler_metrics_requires_operations_metrics_scope(
    api_client: TestClient, holdria_api_key: str
) -> None:
    """tasks.md 6.2: the `operations:metrics` scope is distinct from
    `operations:read` and Holdria does not receive it by default
    (config.settings.Settings.consumer_credentials).
    """

    response = api_client.get("/v1/status/metrics", headers=_auth(holdria_api_key))

    assert response.status_code == 403


def test_scheduler_metrics_reports_sanitized_source_level_data(
    api_client: TestClient, db_session: Session, ops_api_key: str
) -> None:
    db_session.add(
        Job(
            job_type="fetch_range",
            dedupe_key="fake:listing-1:EOD_CLOSE:2020-01-01:2020-01-01",
            source="fake",
            status=JobStatus.PENDING,
            created_at=utcnow() - timedelta(hours=2),
            next_run_at=utcnow(),
        )
    )
    db_session.commit()

    response = api_client.get("/v1/status/metrics", headers=_auth(ops_api_key))

    assert response.status_code == 200
    body = response.json()
    assert body["pending_jobs"] == 1
    assert body["pending_jobs_by_source"] == {"fake": 1}
    assert body["stalled_sources"] == ["fake"]
    assert body["quota_by_source"][0]["source"] == "fake"
    assert body["quota_by_source"][0]["error"] is None
    # tasks.md 6.1: no scheduler cycle ran yet, so the durable execution
    # counts start at zero — distinct from `done_jobs`, a per-job count.
    assert body["scheduler_success_count"] == 0
    assert body["worker_success_count"] == 0


def test_data_status_reports_last_effective_date_and_availability(
    api_client: TestClient, db_session: Session, holdria_api_key: str
) -> None:
    listing = create_equity_listing(db_session)
    approve_publication(db_session, "fake")
    record_observation(db_session, listing, session_date=date(2026, 1, 5))

    response = api_client.get(f"/v1/listings/{listing.id}/status", headers=_auth(holdria_api_key))

    assert response.status_code == 200
    body = response.json()
    assert body["last_effective_date"] == "2026-01-05"
    assert body["listing_id"] == str(listing.id)


def test_data_status_never_reports_a_date_from_an_unresolved_source(
    api_client: TestClient, db_session: Session, holdria_api_key: str
) -> None:
    """tasks.md 6.3; specs/consumer-api/spec.md § "Stored data not
    redistributable": a source with no policy decision at all (`UNRESOLVED`
    — the default when nothing was ever recorded) SHALL never leak the mere
    existence of its stored observations through `last_effective_date`.
    """

    listing = create_equity_listing(db_session)
    record_observation(db_session, listing, session_date=date(2026, 1, 5))
    # Deliberately no `approve_publication`: "fake" stays `UNRESOLVED`.

    response = api_client.get(f"/v1/listings/{listing.id}/status", headers=_auth(holdria_api_key))

    assert response.status_code == 200
    body = response.json()
    assert body["last_effective_date"] is None
    assert body["has_publishable_data"] is False
    assert "2026-01-05" not in response.text


def test_data_status_never_reports_a_date_from_a_denied_source(
    api_client: TestClient, db_session: Session, holdria_api_key: str
) -> None:
    """A `DENIED` capability (here, `REDISTRIBUTE`) blocks publication just
    as effectively as `UNRESOLVED`: the stored observation's session date
    SHALL NOT surface as `last_effective_date` merely because the other two
    capabilities are `APPROVED`.
    """

    listing = create_equity_listing(db_session)
    approve_publication(db_session, "fake")
    deny_capability(db_session, "fake", PolicyCapability.REDISTRIBUTE)
    record_observation(db_session, listing, session_date=date(2026, 1, 5))

    response = api_client.get(f"/v1/listings/{listing.id}/status", headers=_auth(holdria_api_key))

    assert response.status_code == 200
    body = response.json()
    assert body["last_effective_date"] is None
    assert body["has_publishable_data"] is False
    assert "2026-01-05" not in response.text


def test_data_status_stops_reporting_the_effective_date_after_publication_is_revoked(
    api_client: TestClient, db_session: Session, holdria_api_key: str
) -> None:
    """specs/market-observations/spec.md § "Preserved history": a
    revocation recorded *after* an observation was stored SHALL immediately
    stop `last_effective_date` from reflecting it, without mutating or
    deleting the append-only row itself.
    """

    # `has_publishable_data` walks back from the real current date within a
    # bounded lookback window, unlike `last_effective_date`: the observation
    # SHALL be within that window for the "before" assertion to be
    # meaningful.
    today = date.today()
    listing = create_equity_listing(db_session)
    approve_publication(db_session, "fake")
    record_observation(db_session, listing, session_date=today)

    before = api_client.get(f"/v1/listings/{listing.id}/status", headers=_auth(holdria_api_key))
    assert before.json()["last_effective_date"] == today.isoformat()
    assert before.json()["has_publishable_data"] is True

    deny_capability(db_session, "fake", PolicyCapability.DISPLAY)

    after = api_client.get(f"/v1/listings/{listing.id}/status", headers=_auth(holdria_api_key))
    assert after.status_code == 200
    body = after.json()
    assert body["last_effective_date"] is None
    assert body["has_publishable_data"] is False
    assert today.isoformat() not in after.text


def test_data_status_for_unknown_listing_returns_sanitized_404(
    api_client: TestClient, holdria_api_key: str
) -> None:
    response = api_client.get(f"/v1/listings/{uuid.uuid4()}/status", headers=_auth(holdria_api_key))

    assert response.status_code == 404
    assert response.json() == {"detail": "Listing not found."}
