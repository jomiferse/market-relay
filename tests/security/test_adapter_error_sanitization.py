"""A decoy secret embedded in a provider's own exception text SHALL never
reach a metric, a job's persisted error, or a scheduler refresh error, even
in a shape that `sanitize_message`'s regex patterns do not cover (tasks.md
6.2; specs/source-governance/spec.md § "Credential protection").

`sanitize_message` only recognizes a credential embedded in a URL authority
(`https://user:pass@host`) or a `key=value` query parameter. A secret in
any other shape — a bare token in a plain-text sentence, exactly how a real
provider's error body would read — passes straight through it unredacted.
The fix under test here is not sanitizing harder: it is never trusting a
provider's exception text at all for any adapter-originated failure. Every
test below uses that unrecognized shape deliberately, to prove the
production code paths never rely on regex sanitization catching it.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from sqlalchemy.orm import Session

from market_relay.adapters import registry
from market_relay.adapters.fake.provider import FakeMarketDataProvider
from market_relay.config import Settings
from market_relay.domain.catalog import AssetClass, CatalogService
from market_relay.domain.governance import PolicyCapability, PolicyGate, PolicyStatus
from market_relay.domain.governance.credentials import sanitize_message
from market_relay.domain.ingestion.error_codes import ADAPTER_ERROR
from market_relay.domain.ingestion.metrics import collect_scheduler_metrics
from market_relay.domain.ingestion.planning import RecoveryLimits
from market_relay.domain.ingestion.queue import JobQueue
from market_relay.domain.ingestion.runner import IngestionRunner
from market_relay.domain.ingestion.scheduler_service import claim_and_process, refresh_and_dispatch
from market_relay.domain.observations.service import ObservationStore
from market_relay.ports.calendar import SessionCheck
from market_relay.ports.historical import RawObservation
from market_relay.ports.quota import QuotaStatus

NOW = datetime(2026, 1, 9, 10, 0, tzinfo=UTC)
LIMITS = RecoveryLimits(max_lookback_days=10, max_sessions_per_chunk=5)

# A shape `sanitize_message` does not recognize: a bare token in a plain
# sentence, not a URL authority and not a `key=value` query parameter.
DECOY_SECRET = "sk_live_DECOY_plain_9f3ac0e1"  # nosec: decoy test value


def test_sanitize_message_does_not_redact_a_plain_text_decoy_secret() -> None:
    """Documents the actual gap: this shape of secret is exactly what
    regex-only sanitization misses, which is why adapter-originated errors
    never rely on `sanitize_message` alone.
    """

    message = f"provider rejected credential {DECOY_SECRET}"

    assert DECOY_SECRET in sanitize_message(message)


class _DecoyQuotaProvider(FakeMarketDataProvider):
    """A fake adapter whose quota check raises with a decoy secret embedded
    in the exception text, exactly as a real provider's client library
    might.
    """

    def check(self, source: str) -> QuotaStatus:
        raise RuntimeError(f"quota endpoint rejected credential '{DECOY_SECRET}'")


class _DecoyCalendarProvider(FakeMarketDataProvider):
    """A fake adapter whose calendar lookup raises with a decoy secret."""

    def sessions_in_range(self, **_kwargs: object) -> list[SessionCheck]:
        raise RuntimeError(f"calendar endpoint rejected credential '{DECOY_SECRET}'")


class _DecoyFetchProvider(FakeMarketDataProvider):
    """A fake adapter whose historical fetch raises with a decoy secret."""

    def fetch_range(
        self, *, external_listing_id: str, start: date, end: date
    ) -> list[RawObservation]:
        raise RuntimeError(f"fetch endpoint rejected credential '{DECOY_SECRET}'")


def _approve_ingestion(session: Session, source: str) -> None:
    gate = PolicyGate(session)
    for capability in (PolicyCapability.RETRIEVE, PolicyCapability.STORE):
        gate.record_decision(
            source=source,
            capability=capability,
            status=PolicyStatus.APPROVED,
            evidence_reference=f"https://{source}.example/terms#{capability.value.lower()}",
            reviewed_by="ops@holdria.test",
        )


def test_a_quota_adapter_decoy_secret_never_reaches_the_metrics_error_field(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(registry._ADAPTERS, "decoy-quota", _DecoyQuotaProvider())

    snapshot = collect_scheduler_metrics(
        session=db_session, now=NOW, stalled_threshold_seconds=3600, sources=("decoy-quota",)
    )

    error = snapshot.quota_by_source[0].error
    assert error == ADAPTER_ERROR
    assert DECOY_SECRET not in (error or "")


def test_a_calendar_adapter_decoy_secret_never_reaches_a_refresh_error(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalog = CatalogService(db_session)
    instrument = catalog.register_instrument(
        asset_class=AssetClass.EQUITY, name="Decoy Corp", isin="DE0007164699"
    )
    listing = catalog.add_listing(
        instrument=instrument, venue="XETR", mic="XETR", ticker="DCY", currency="EUR"
    )
    catalog.link_external_identity(
        listing=listing,
        source="decoy-calendar",
        external_id="DECOY-DCY",
        valid_from=date(2025, 1, 1),
    )
    db_session.commit()
    _approve_ingestion(db_session, "decoy-calendar")
    monkeypatch.setitem(registry._ADAPTERS, "decoy-calendar", _DecoyCalendarProvider())
    monkeypatch.setitem(registry._CALENDAR_ROUTES, "XETR", "decoy-calendar")

    settings = Settings(enabled_sources=("decoy-calendar",), scheduler_batch_size=50)
    outcome = refresh_and_dispatch(
        session=db_session,
        settings=settings,
        now=NOW,
        max_listings_per_source=10,
        recovery_limits=LIMITS,
    )

    assert outcome.refresh_errors
    assert all(DECOY_SECRET not in error for error in outcome.refresh_errors)
    assert all(ADAPTER_ERROR in error for error in outcome.refresh_errors)


def test_a_fetch_adapter_decoy_secret_never_reaches_the_persisted_job_error(
    db_session: Session,
) -> None:
    from market_relay.domain.ingestion.cursor import FetchCursor
    from market_relay.domain.observations.models import Job, JobStatus, ObservationType

    cursor = FetchCursor(
        external_listing_id="DECOY-DCY",
        credential_scope="default",
        observation_type=ObservationType.EOD_CLOSE,
        start=date(2026, 1, 1),
        end=date(2026, 1, 1),
    )
    job = Job(
        job_type="fetch_range",
        dedupe_key="decoy-fetch:listing:EOD_CLOSE:2026-01-01:2026-01-01",
        source="decoy-fetch",
        status=JobStatus.CLAIMED,
        claimed_by="test-worker",
        claimed_at=NOW,
        cursor=cursor.serialize(),
        next_run_at=NOW,
    )
    db_session.add(job)
    db_session.commit()

    _approve_ingestion(db_session, "decoy-fetch")

    runner = IngestionRunner(
        provider=_DecoyFetchProvider(),
        policy_gate=PolicyGate(db_session),
        queue=JobQueue(db_session),
        store=ObservationStore(db_session),
    )

    runner.process(job, worker_id="test-worker", now=NOW)

    assert job.last_error == ADAPTER_ERROR
    assert DECOY_SECRET not in (job.last_error or "")


def test_a_claim_and_process_unexpected_failure_decoy_secret_never_reaches_the_job_error(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`claim_and_process`'s own catch-all — for a failure resolving or
    constructing the adapter, not one raised from inside `IngestionRunner`
    — is a second, independent place a provider's raw exception text could
    have leaked into a persisted job error. It must use
    `adapter_error_code`, exactly like every other adapter-originated
    failure path, never `sanitize_message(str(exc))`.
    """

    from market_relay.domain.ingestion.cursor import FetchCursor
    from market_relay.domain.observations.models import Job, JobStatus, ObservationType

    cursor = FetchCursor(
        external_listing_id="DECOY-DCY",
        credential_scope="default",
        observation_type=ObservationType.EOD_CLOSE,
        start=date(2026, 1, 1),
        end=date(2026, 1, 1),
    )
    job = Job(
        job_type="fetch_range",
        dedupe_key="decoy-claim:listing:EOD_CLOSE:2026-01-01:2026-01-01",
        source="decoy-claim",
        status=JobStatus.PENDING,
        cursor=cursor.serialize(),
        next_run_at=NOW,
    )
    db_session.add(job)
    db_session.commit()

    def _raise_with_decoy_secret(source: str) -> object:
        raise RuntimeError(f"adapter resolution rejected credential '{DECOY_SECRET}'")

    monkeypatch.setattr(
        "market_relay.domain.ingestion.scheduler_service.get_historical_price_port",
        _raise_with_decoy_secret,
    )

    settings = Settings(enabled_sources=("decoy-claim",), scheduler_batch_size=50)
    outcome = claim_and_process(session=db_session, settings=settings, now=NOW, batch_size=10)

    assert outcome.jobs_claimed == 1
    assert job.last_error == ADAPTER_ERROR
    assert DECOY_SECRET not in (job.last_error or "")
