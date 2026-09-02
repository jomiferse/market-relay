"""Translates the observations domain into the HTTP v1 contract (tasks.md 5.3).

Applies the publication policy gate on every response: a stored observation
whose source lacks current `STORE`+`DISPLAY`+`REDISTRIBUTE` never reaches
`ObservationOut.value` (specs/consumer-api/spec.md § "Stored
non-redistributable data"; specs/market-observations/spec.md §
"Preserved history" — a revoked source stops appearing in ordinary
responses without mutating any row). Absence of session and waiting for
publication are represented explicitly instead of being mixed with "no
data" (specs/consumer-api/spec.md § "Range with non-trading days").
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from market_relay.api.schemas import ObservationAvailability, ObservationOut, ObservationValueOut
from market_relay.config import Settings
from market_relay.domain.catalog.models import Listing
from market_relay.domain.governance.policy_gate import PolicyGate
from market_relay.domain.observations.models import Observation, ObservationType
from market_relay.domain.observations.selection import (
    NoEligibleObservationError,
    ObservationSelector,
    SourcePriorityPolicy,
)
from market_relay.ports.calendar import MarketCalendarPort, SessionExpectation

# Bounded lookback window for "latest observation": avoids an unbounded
# scan when a listing never had publishable data.
_LATEST_LOOKBACK_DAYS = 10

_AVAILABILITY_BY_EXPECTATION: dict[SessionExpectation, ObservationAvailability] = {
    SessionExpectation.NO_SESSION: ObservationAvailability.NO_SESSION,
    SessionExpectation.WAITING_FOR_PUBLICATION: ObservationAvailability.WAITING_FOR_PUBLICATION,
    SessionExpectation.EXPECTED_PUBLISHED: ObservationAvailability.UNAVAILABLE,
}


def priority_policy(settings: Settings) -> SourcePriorityPolicy:
    """Deterministic priority policy: the order of `enabled_sources`.

    There is never implicit resolution: a source absent from
    `enabled_sources` is never considered, even if it has publishable
    observations stored (specs/market-observations/spec.md § "Deterministic
    selection without silent mixing").
    """

    return SourcePriorityPolicy(name="configured-sources", ordered_sources=settings.enabled_sources)


def _session_expectation(
    calendar: MarketCalendarPort, listing: Listing, session_date: date
) -> SessionExpectation:
    checks = calendar.sessions_in_range(
        asset_class=listing.instrument.asset_class,
        venue=listing.venue,
        mic=listing.mic,
        start=session_date,
        end=session_date,
    )
    return checks[0].expectation


def _attribution_for(gate: PolicyGate, source: str) -> tuple[bool, str | None]:
    requires = gate.requires_attribution(source)
    return requires, (f"Source: {source}." if requires else None)


def build_observation_out(
    *,
    session: Session,
    listing: Listing,
    session_date: date,
    observation_type: ObservationType,
    settings: Settings,
    calendar: MarketCalendarPort,
    policy_gate: PolicyGate | None = None,
) -> ObservationOut:
    """Publishable observation for `listing` on `session_date`, or the
    explicit state of its absence (`NO_SESSION`, `WAITING_FOR_PUBLICATION`,
    `UNAVAILABLE`) when there is none.
    """

    gate = policy_gate if policy_gate is not None else PolicyGate(session)
    selector = ObservationSelector(session, gate)
    try:
        result = selector.select(
            listing_id=listing.id,
            session_date=session_date,
            observation_type=observation_type,
            policy=priority_policy(settings),
        )
    except NoEligibleObservationError:
        expectation = _session_expectation(calendar, listing, session_date)
        return ObservationOut(
            listing_id=listing.id,
            session_date=session_date,
            availability=_AVAILABILITY_BY_EXPECTATION[expectation],
            value=None,
        )

    observation = result.selected
    requires_attribution, attribution = _attribution_for(gate, observation.source)
    value = ObservationValueOut(
        observation_type=observation.observation_type,
        currency=observation.currency,
        close=observation.close,
        source=observation.source,
        revision=observation.revision,
        retrieved_at=observation.retrieved_at,
        requires_attribution=requires_attribution,
        attribution=attribution,
        has_discrepancy=result.has_discrepancy,
    )
    return ObservationOut(
        listing_id=listing.id,
        session_date=session_date,
        availability=ObservationAvailability.OK,
        value=value,
    )


def find_latest_observation(
    *,
    session: Session,
    listing: Listing,
    observation_type: ObservationType,
    settings: Settings,
    calendar: MarketCalendarPort,
    today: date | None = None,
) -> ObservationOut:
    """The most recent publishable observation within a bounded window.

    Walks backward from `today` (the current date by default) until it
    finds the first date with an `OK` observation. If no date in the
    window has publishable data, returns the explicit state of `today`
    instead of feigning total absence (specs/consumer-api/spec.md §
    "EOD price request": the response always identifies its effective
    date and EOD nature).
    """

    reference_today = today if today is not None else date.today()
    gate = PolicyGate(session)
    for offset in range(_LATEST_LOOKBACK_DAYS + 1):
        candidate_date = reference_today - timedelta(days=offset)
        out = build_observation_out(
            session=session,
            listing=listing,
            session_date=candidate_date,
            observation_type=observation_type,
            settings=settings,
            calendar=calendar,
            policy_gate=gate,
        )
        if out.availability is ObservationAvailability.OK:
            return out

    return build_observation_out(
        session=session,
        listing=listing,
        session_date=reference_today,
        observation_type=observation_type,
        settings=settings,
        calendar=calendar,
        policy_gate=gate,
    )


def latest_publishable_session_date(
    *,
    session: Session,
    listing: Listing,
    observation_type: ObservationType,
    settings: Settings,
    policy_gate: PolicyGate | None = None,
) -> date | None:
    """The most recent `session_date` with a currently publishable
    observation, or `None` if there is none.

    `/v1/listings/{id}/status` (`api.routers.status.data_status`) SHALL
    never derive its "last effective date" from every stored observation
    regardless of source: an observation from a source whose publication
    authorization is `DENIED`, `UNRESOLVED`, or was later revoked would then
    leak metadata about data the consumer is not authorized to see — the
    session it exists for, even without ever exposing its `value`
    (specs/consumer-api/spec.md § "Stored non-redistributable data"). This
    restricts the search to the exact same `STORE`+`DISPLAY`+`REDISTRIBUTE`
    authorization and `settings.enabled_sources` priority that
    `ObservationSelector`/`build_observation_out` apply to every value
    response, so the reported date is always one for which `select()` would
    actually succeed.

    A source's authorization does not depend on `session_date`, so it is
    enough to compute the currently authorized subset of
    `settings.enabled_sources` once and take the maximum stored
    `session_date` among rows from those sources — no unbounded per-day
    scan is needed, unlike `find_latest_observation`'s bounded lookback for
    the *value* response.
    """

    gate = policy_gate if policy_gate is not None else PolicyGate(session)
    authorized_sources = [
        source for source in settings.enabled_sources if gate.is_publication_authorized(source)
    ]
    if not authorized_sources:
        return None

    return session.scalar(
        select(func.max(Observation.session_date)).where(
            Observation.listing_id == listing.id,
            Observation.observation_type == observation_type,
            Observation.source.in_(authorized_sources),
        )
    )


def build_observation_range(
    *,
    session: Session,
    listing: Listing,
    observation_type: ObservationType,
    start: date,
    end: date,
    settings: Settings,
    calendar: MarketCalendarPort,
) -> list[ObservationOut]:
    """One `ObservationOut` per date in `[start, end]`, in order."""

    gate = PolicyGate(session)
    results: list[ObservationOut] = []
    current = start
    while current <= end:
        results.append(
            build_observation_out(
                session=session,
                listing=listing,
                session_date=current,
                observation_type=observation_type,
                settings=settings,
                calendar=calendar,
                policy_gate=gate,
            )
        )
        current += timedelta(days=1)
    return results
