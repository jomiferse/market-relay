"""Bounded range-based recovery planning with a persistent cursor.

`specs/market-data-ingestion/spec.md` § "Range-based recovery" requires
requesting from the last completed session up to the last session whose
publication is expected, respecting age and size limits, and retrieving
several missing sessions in bounded jobs. § "Calendar and publication by
class" requires not consuming quota on `NO_SESSION` dates and representing
`WAITING_FOR_PUBLICATION` as waiting, not as a failure.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from market_relay.domain.catalog.models import AssetClass
from market_relay.ports.calendar import MarketCalendarPort, SessionExpectation


@dataclass(frozen=True, slots=True)
class RecoveryLimits:
    """Configured age and size limits (design.md § "Range-based recovery").
    Both bound how much work a single planning run generates.
    """

    max_lookback_days: int = 365
    max_sessions_per_chunk: int = 20


@dataclass(frozen=True, slots=True)
class RecoveryChunk:
    """A bounded segment of `EXPECTED_PUBLISHED` sessions to retrieve."""

    start: date
    end: date
    session_dates: tuple[date, ...]


@dataclass(frozen=True, slots=True)
class RecoveryPlan:
    """Result of planning the recovery of a listing.

    `next_cursor` is the *safe* resumption point, not the last day
    considered: it only advances over a contiguous prefix of `NO_SESSION`
    dates immediately following `last_completed_session`, because those
    dates never require a data point and never need retrying. It never
    advances over an `EXPECTED_PUBLISHED` date (even if it was already
    dispatched in a `RecoveryChunk`: dispatching a job is not completing it)
    nor over a `WAITING_FOR_PUBLICATION` date — otherwise, a later planning
    run that uses `next_cursor` as the new `last_completed_session` would
    permanently skip a NAV that has not yet been published
    (specs/market-data-ingestion/spec.md § "NAV not yet published"). The
    real durable progress — what was actually completed — is derived from
    the observations and jobs actually persisted
    (`ObservationStore.last_completed_session`), never from this field:
    `next_cursor` only avoids repeating planning work over segments that are
    certain to need no data at all.
    """

    chunks: tuple[RecoveryChunk, ...]
    waiting_for_publication: tuple[date, ...]
    skipped_no_session: tuple[date, ...]
    next_cursor: date | None

    @property
    def total_expected_sessions(self) -> int:
        return sum(len(chunk.session_dates) for chunk in self.chunks)


class RecoveryPlanner:
    """Translates a listing's calendar into bounded, ordered work."""

    def __init__(self, calendar: MarketCalendarPort, limits: RecoveryLimits | None = None) -> None:
        self._calendar = calendar
        self._limits = limits or RecoveryLimits()

    def plan(
        self,
        *,
        asset_class: AssetClass,
        venue: str,
        mic: str | None,
        last_completed_session: date | None,
        today: date,
    ) -> RecoveryPlan:
        """Computes the pending bounded range `[start, end]` and splits it
        into size-limited `RecoveryChunk`s, without fabricating work for
        `NO_SESSION` dates and without treating `WAITING_FOR_PUBLICATION` as
        a failure.
        """

        earliest_allowed = today - timedelta(days=self._limits.max_lookback_days)
        if last_completed_session is None:
            start = earliest_allowed
        else:
            start = max(last_completed_session + timedelta(days=1), earliest_allowed)

        if start > today:
            return RecoveryPlan(
                chunks=(),
                waiting_for_publication=(),
                skipped_no_session=(),
                next_cursor=last_completed_session,
            )

        checks = sorted(
            self._calendar.sessions_in_range(
                asset_class=asset_class, venue=venue, mic=mic, start=start, end=today
            ),
            key=lambda check: check.session_date,
        )

        expected: list[date] = []
        waiting: list[date] = []
        skipped: list[date] = []
        for check in checks:
            if check.expectation is SessionExpectation.EXPECTED_PUBLISHED:
                expected.append(check.session_date)
            elif check.expectation is SessionExpectation.WAITING_FOR_PUBLICATION:
                waiting.append(check.session_date)
            else:
                skipped.append(check.session_date)

        chunks: list[RecoveryChunk] = []
        chunk_size = self._limits.max_sessions_per_chunk
        for offset in range(0, len(expected), chunk_size):
            group = tuple(expected[offset : offset + chunk_size])
            chunks.append(RecoveryChunk(start=group[0], end=group[-1], session_dates=group))

        # Only advances over the contiguous `NO_SESSION` prefix: it stops at
        # the first date that requires real data (`EXPECTED_PUBLISHED`) or
        # is still waiting (`WAITING_FOR_PUBLICATION`), so that a later
        # resumption reconsiders it instead of skipping it.
        next_cursor = last_completed_session
        for check in checks:
            if check.expectation is not SessionExpectation.NO_SESSION:
                break
            next_cursor = check.session_date

        return RecoveryPlan(
            chunks=tuple(chunks),
            waiting_for_publication=tuple(waiting),
            skipped_no_session=tuple(skipped),
            next_cursor=next_cursor,
        )
