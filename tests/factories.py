"""Data factories shared by the v1 API tests (tasks.md 5).

Centralizes the construction of instruments, listings, approved policies and
observations so the API's integration, contract and security tests do not
replicate the same domain boilerplate.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from market_relay.domain.catalog.models import AssetClass, Listing
from market_relay.domain.catalog.service import CatalogService
from market_relay.domain.governance.models import PolicyCapability, PolicyStatus
from market_relay.domain.governance.policy_gate import PolicyGate
from market_relay.domain.observations.models import ObservationType, QualityStatus
from market_relay.domain.observations.service import ObservationInput, ObservationStore

PUBLICATION_CAPABILITIES = (
    PolicyCapability.RETRIEVE,
    PolicyCapability.STORE,
    PolicyCapability.DISPLAY,
    PolicyCapability.REDISTRIBUTE,
)


def approve_publication(session: Session, source: str, *, attribute: bool = False) -> None:
    """Approves `RETRIEVE`+`STORE`+`DISPLAY`+`REDISTRIBUTE` for `source`.

    Sufficient for `PolicyGate.is_publication_authorized` to return
    `True` (specs/source-governance/spec.md).
    """

    gate = PolicyGate(session)
    capabilities = (
        (*PUBLICATION_CAPABILITIES, PolicyCapability.ATTRIBUTE)
        if attribute
        else (PUBLICATION_CAPABILITIES)
    )
    for capability in capabilities:
        gate.record_decision(
            source=source,
            capability=capability,
            status=PolicyStatus.APPROVED,
            evidence_reference=f"https://{source}.example/terms#{capability.value.lower()}",
            reviewed_by="ops@holdria.test",
        )


def deny_capability(session: Session, source: str, capability: PolicyCapability) -> None:
    PolicyGate(session).record_decision(
        source=source,
        capability=capability,
        status=PolicyStatus.DENIED,
        evidence_reference=f"https://{source}.example/terms/revoked#{capability.value.lower()}",
        reviewed_by="ops@holdria.test",
    )


def create_equity_listing(
    session: Session,
    *,
    name: str = "SAP SE",
    isin: str = "DE0007164600",
    venue: str = "XETR",
    mic: str = "XETR",
    ticker: str = "SAP",
    currency: str = "EUR",
) -> Listing:
    catalog = CatalogService(session)
    instrument = catalog.register_instrument(asset_class=AssetClass.EQUITY, name=name, isin=isin)
    listing = catalog.add_listing(
        instrument=instrument, venue=venue, mic=mic, ticker=ticker, currency=currency
    )
    session.commit()
    return listing


def create_fund_listing(
    session: Session,
    *,
    name: str = "Amundi MSCI World UCITS ETF",
    isin: str = "LU1681043599",
    venue: str = "XETR",
    ticker: str = "AMD",
    currency: str = "EUR",
) -> Listing:
    catalog = CatalogService(session)
    instrument = catalog.register_instrument(asset_class=AssetClass.FUND, name=name, isin=isin)
    listing = catalog.add_listing(
        instrument=instrument, venue=venue, ticker=ticker, currency=currency
    )
    session.commit()
    return listing


def record_observation(
    session: Session,
    listing: Listing,
    *,
    session_date: date,
    close: str = "123.45",
    source: str = "fake",
    credential_scope: str = "default",
    external_listing_id: str | None = None,
    observation_type: ObservationType = ObservationType.EOD_CLOSE,
    retrieved_at: datetime | None = None,
    quality_status: QualityStatus = QualityStatus.OK,
) -> None:
    store = ObservationStore(session)
    store.record(
        ObservationInput(
            listing_id=listing.id,
            source=source,
            credential_scope=credential_scope,
            external_listing_id=external_listing_id or f"{source}:{listing.ticker}",
            session_date=session_date,
            observation_type=observation_type,
            currency=listing.currency,
            close=Decimal(close),
            retrieved_at=retrieved_at or datetime(2026, 1, 2, 18, 0),
            quality_status=quality_status,
        )
    )
    session.commit()
