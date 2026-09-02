"""A non-cooperative provider cannot exceed the scheduler deadline."""

from __future__ import annotations

import time
from datetime import UTC, date, datetime

from market_relay.adapters.fake.provider import FakeMarketDataProvider
from market_relay.domain.catalog import AssetClass, CatalogService
from market_relay.domain.governance import PolicyCapability, PolicyGate, PolicyStatus
from market_relay.domain.ingestion import IngestionRunner, JobQueue
from market_relay.domain.ingestion.cursor import FetchCursor
from market_relay.domain.observations.models import JobStatus, ObservationType
from market_relay.domain.observations.service import ObservationStore
from market_relay.ports.historical import RawObservation

NOW = datetime(2026, 1, 5, 18, 0, tzinfo=UTC)


class BlockingProvider:
    def fetch_range(
        self, *, external_listing_id: str, start: date, end: date
    ) -> list[RawObservation]:
        time.sleep(30)
        return []


def test_hanging_provider_is_terminated_and_retried_with_safe_code(db_session) -> None:
    catalog = CatalogService(db_session)
    instrument = catalog.register_instrument(
        asset_class=AssetClass.EQUITY, name="Timeout Test", isin="DE0000000099"
    )
    listing = catalog.add_listing(
        instrument=instrument, venue="XETR", mic="XETR", ticker="TIME", currency="EUR"
    )
    gate = PolicyGate(db_session)
    for capability in (PolicyCapability.RETRIEVE, PolicyCapability.STORE):
        gate.record_decision(
            source="blocking",
            capability=capability,
            status=PolicyStatus.APPROVED,
            evidence_reference="internal:test-only",
            reviewed_by="test-suite",
            reviewed_at=NOW,
        )
    queue = JobQueue(db_session)
    cursor = FetchCursor(
        external_listing_id="BLOCKING-ID",
        credential_scope="default",
        observation_type=ObservationType.EOD_CLOSE,
        start=NOW.date(),
        end=NOW.date(),
    )
    job = queue.enqueue_idempotent(
        job_type="fetch_range",
        source="blocking",
        dedupe_key="blocking-timeout",
        listing_id=listing.id,
        cursor=cursor.serialize(),
        run_at=NOW,
    ).job
    runner = IngestionRunner(
        provider=BlockingProvider(),
        quota=FakeMarketDataProvider(),
        policy_gate=gate,
        queue=queue,
        store=ObservationStore(db_session),
        timeout_seconds=0.1,
    )

    started = time.monotonic()
    outcome = runner.process(job, worker_id="timeout-worker", now=NOW)
    elapsed = time.monotonic() - started

    assert elapsed < 2
    assert outcome.detail == "fetch_error"
    assert job.status == JobStatus.PENDING
    assert job.attempt_count == 1
    assert job.last_error == "provider_timeout"
