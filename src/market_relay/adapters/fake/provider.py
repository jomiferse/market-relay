"""Deterministic fake provider: covers the full flow without network or secrets.

`specs/source-governance/spec.md` § "Safe test adapters" requires a source
that needs no external access or real credentials and that, run twice with
the same scenario, produces the same observations and effective states.
This adapter implements the four neutral ports (discovery, historical,
calendar, quota) using only deterministic arithmetic over its inputs — never
`random` without a seed nor the system clock.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from market_relay.domain.catalog.models import AssetClass
from market_relay.domain.observations.models import ObservationType
from market_relay.ports.calendar import SessionCheck, SessionExpectation
from market_relay.ports.discovery import DiscoveredIdentity, DiscoveryQuery
from market_relay.ports.historical import RawObservation
from market_relay.ports.quota import QuotaStatus

SOURCE_NAME = "fake"

# Static embedded catalog: known identities of the fake provider, with no
# credentials or network calls. Covers the OpenSpec cases cited in
# tasks.md 2.4: one-to-many (same ISIN in two markets) and crypto without ISIN.
_FAKE_IDENTITIES: tuple[DiscoveredIdentity, ...] = (
    DiscoveredIdentity(
        source=SOURCE_NAME,
        external_id="FAKE-DE0007164600-XETR",
        name="SAP SE",
        asset_class=AssetClass.EQUITY,
        ticker="SAP",
        venue="XETR",
        currency="EUR",
        isin="DE0007164600",
        mic="XETR",
    ),
    DiscoveredIdentity(
        source=SOURCE_NAME,
        external_id="FAKE-DE0007164600-XPAR",
        name="SAP SE",
        asset_class=AssetClass.EQUITY,
        ticker="SAP",
        venue="XPAR",
        currency="EUR",
        isin="DE0007164600",
        mic="XPAR",
    ),
    DiscoveredIdentity(
        source=SOURCE_NAME,
        external_id="FAKE-BTC-KRAKEN",
        name="Bitcoin",
        asset_class=AssetClass.CRYPTO,
        ticker="BTC",
        venue="KRAKEN",
        currency="EUR",
        isin=None,
        mic=None,
    ),
)


def _deterministic_price(seed: str, *, base: Decimal, spread: Decimal) -> Decimal:
    """Derives a reproducible price from a text seed, without `random`.

    Uses SHA-256 to obtain a stable integer from the seed and maps it
    linearly to `[base, base + spread]`. The same input always produces
    the same output, in any process and on any operating system.
    """

    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    ratio = int(digest[:8], 16) / 0xFFFFFFFF
    value = base + spread * Decimal(str(ratio))
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass
class FakeQuotaBook:
    """In-memory quota state for the process, reset per instance.

    Deliberately not persisted across runs: the fake provider never
    represents real quota, it only lets the `QuotaPort` be exercised.
    """

    limit: int = 1000
    _consumed: dict[str, int] = field(default_factory=dict)

    def check(self, source: str) -> QuotaStatus:
        consumed = self._consumed.get(source, 0)
        return QuotaStatus(source=source, remaining=max(self.limit - consumed, 0), limit=self.limit)

    def consume(self, source: str, *, cost: int = 1) -> QuotaStatus:
        status = self.check(source)
        if status.exhausted:
            return status
        self._consumed[source] = self._consumed.get(source, 0) + cost
        return self.check(source)


class FakeMarketDataProvider:
    """Implements `DiscoveryPort`, `HistoricalPricePort`, `MarketCalendarPort`
    and `QuotaPort` deterministically, with no network or real credentials.
    """

    name = SOURCE_NAME

    def __init__(self, quota_book: FakeQuotaBook | None = None) -> None:
        self._quota = quota_book or FakeQuotaBook()

    # -- DiscoveryPort --------------------------------------------------

    def search(self, query: DiscoveryQuery) -> list[DiscoveredIdentity]:
        needle = query.query.strip().upper()
        results = [
            identity
            for identity in _FAKE_IDENTITIES
            if needle in (identity.isin or "") or needle == identity.ticker
        ]
        if query.asset_class is not None:
            results = [r for r in results if r.asset_class == query.asset_class]
        if query.currency is not None:
            results = [r for r in results if r.currency == query.currency.upper()]
        if query.mic is not None:
            results = [r for r in results if r.mic == query.mic]
        return results

    # -- HistoricalPricePort ---------------------------------------------

    def fetch_range(
        self, *, external_listing_id: str, start: date, end: date
    ) -> list[RawObservation]:
        observations: list[RawObservation] = []
        current = start
        while current <= end:
            if current.weekday() < 5:  # no weekends in the fake exchange
                seed = f"{external_listing_id}|{current.isoformat()}"
                close = _deterministic_price(seed, base=Decimal("10.00"), spread=Decimal("90.00"))
                observations.append(
                    RawObservation(
                        external_listing_id=external_listing_id,
                        session_date=current,
                        observation_type=ObservationType.EOD_CLOSE,
                        currency="EUR",
                        close=close,
                        open=close,
                        high=close,
                        low=close,
                        adjusted_close=close,
                    )
                )
            current += timedelta(days=1)
        return observations

    # -- MarketCalendarPort ------------------------------------------------

    def sessions_in_range(
        self,
        *,
        asset_class: AssetClass,
        venue: str,
        mic: str | None,
        start: date,
        end: date,
    ) -> list[SessionCheck]:
        checks: list[SessionCheck] = []
        current = start
        while current <= end:
            checks.append(SessionCheck(current, self._expectation(asset_class, current)))
            current += timedelta(days=1)
        return checks

    @staticmethod
    def _expectation(asset_class: AssetClass, session_date: date) -> SessionExpectation:
        if asset_class is AssetClass.CRYPTO:
            # 24/7: there is always a session and it is always published.
            return SessionExpectation.EXPECTED_PUBLISHED
        if session_date.weekday() >= 5:
            return SessionExpectation.NO_SESSION
        # The fake simulates that Friday's NAV is still within its publication
        # window, to exercise WAITING_FOR_PUBLICATION deterministically
        # without depending on the system clock.
        if asset_class is AssetClass.FUND and session_date.weekday() == 4:
            return SessionExpectation.WAITING_FOR_PUBLICATION
        return SessionExpectation.EXPECTED_PUBLISHED

    # -- QuotaPort -----------------------------------------------------

    def check(self, source: str) -> QuotaStatus:
        return self._quota.check(source)

    def consume(self, source: str, *, cost: int = 1) -> QuotaStatus:
        return self._quota.consume(source, cost=cost)
