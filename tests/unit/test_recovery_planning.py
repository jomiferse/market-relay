"""Recovery planning in bounded ranges (tasks.md 4.4)."""

from __future__ import annotations

from datetime import date

from market_relay.adapters.fake.provider import FakeMarketDataProvider
from market_relay.domain.catalog import AssetClass
from market_relay.domain.ingestion import RecoveryLimits, RecoveryPlanner
from market_relay.ports.calendar import SessionExpectation

# 2026-01-05 is a Monday; with this anchor the fake market treats Sat/Sun as
# NO_SESSION and, for funds, Fridays as WAITING_FOR_PUBLICATION.


def test_several_missed_sessions_are_recovered_in_bounded_chunks() -> None:
    """specs/market-data-ingestion/spec.md § 'Several missing sessions': the
    service was down for several sessions and the next planning run
    recovers the pending range in bounded jobs.
    """

    provider = FakeMarketDataProvider()
    planner = RecoveryPlanner(
        provider, RecoveryLimits(max_lookback_days=365, max_sessions_per_chunk=3)
    )

    plan = planner.plan(
        asset_class=AssetClass.EQUITY,
        venue="XETR",
        mic="XETR",
        last_completed_session=date(2025, 12, 29),  # Monday
        today=date(2026, 1, 9),  # following Friday: 8 calendar days missing
    )

    # 2025-12-30, 31, 2026-01-01..02 (Tue-Fri) + 2026-01-05..09 (Mon-Fri) =
    # 9 expected business days, no weekends.
    assert plan.total_expected_sessions == 9
    assert len(plan.chunks) == 3  # bounded to 3 sessions per job: 3+3+3
    assert [len(chunk.session_dates) for chunk in plan.chunks] == [3, 3, 3]
    assert plan.chunks[0].session_dates[0] == date(2025, 12, 30)
    assert plan.chunks[-1].session_dates[-1] == date(2026, 1, 9)
    # `next_cursor` does NOT advance over EXPECTED_PUBLISHED sessions that
    # are only dispatched (not completed): the first day of the pending
    # range is already a market session (2025-12-30), so the safe cursor
    # stays at `last_completed_session` until a persisted observation
    # confirms real progress.
    assert plan.next_cursor == date(2025, 12, 29)


def test_closed_market_dates_are_skipped_not_planned() -> None:
    """specs/market-data-ingestion/spec.md § 'Closed market': no quota is
    consumed requesting a price for a date with no session.
    """

    provider = FakeMarketDataProvider()
    planner = RecoveryPlanner(
        provider, RecoveryLimits(max_lookback_days=365, max_sessions_per_chunk=10)
    )

    plan = planner.plan(
        asset_class=AssetClass.EQUITY,
        venue="XETR",
        mic="XETR",
        last_completed_session=date(2026, 1, 2),  # Friday
        today=date(2026, 1, 5),  # following Monday
    )

    # 2026-01-03 (Sat) and 2026-01-04 (Sun) are NO_SESSION.
    assert date(2026, 1, 3) in plan.skipped_no_session
    assert date(2026, 1, 4) in plan.skipped_no_session
    all_planned_dates = {d for chunk in plan.chunks for d in chunk.session_dates}
    assert date(2026, 1, 3) not in all_planned_dates
    assert date(2026, 1, 4) not in all_planned_dates
    assert date(2026, 1, 5) in all_planned_dates
    # `next_cursor` CAN advance over a contiguous NO_SESSION prefix
    # (a weekend): those dates never require a data point and never need
    # retrying. It stops at 2026-01-04 (Sunday), right before Monday's
    # EXPECTED_PUBLISHED session, which is not yet completed.
    assert plan.next_cursor == date(2026, 1, 4)


def test_fund_nav_waiting_for_publication_is_not_an_error() -> None:
    """specs/market-data-ingestion/spec.md § 'NAV not yet published':
    within the expected publication window, `WAITING_FOR_PUBLICATION`
    does not count as a failure nor is it mixed with already publishable
    sessions.
    """

    provider = FakeMarketDataProvider()
    planner = RecoveryPlanner(
        provider, RecoveryLimits(max_lookback_days=365, max_sessions_per_chunk=10)
    )

    plan = planner.plan(
        asset_class=AssetClass.FUND,
        venue="LU-FUNDS",
        mic=None,
        last_completed_session=date(2026, 1, 1),
        today=date(2026, 1, 9),  # Friday: the fake marks Fridays as waiting
    )

    assert date(2026, 1, 9) in plan.waiting_for_publication
    all_planned_dates = {d for chunk in plan.chunks for d in chunk.session_dates}
    assert date(2026, 1, 9) not in all_planned_dates


def test_waiting_for_publication_is_never_skipped_by_next_cursor() -> None:
    """`next_cursor` SHALL NOT advance over a `WAITING_FOR_PUBLICATION`
    session, nor over any `EXPECTED_PUBLISHED` session after it: if it did,
    a resumption using `next_cursor` as the new `last_completed_session`
    would permanently skip the NAV that has not yet been published
    (specs/market-data-ingestion/spec.md § "NAV not yet published"). Real
    durable progress is derived from observations actually persisted,
    never from this planning field.
    """

    provider = FakeMarketDataProvider()
    planner = RecoveryPlanner(
        provider, RecoveryLimits(max_lookback_days=365, max_sessions_per_chunk=10)
    )

    first_plan = planner.plan(
        asset_class=AssetClass.FUND,
        venue="LU-FUNDS",
        mic=None,
        last_completed_session=date(2026, 1, 1),
        today=date(2026, 1, 9),  # Friday: the fake marks Fridays as waiting
    )

    assert date(2026, 1, 9) in first_plan.waiting_for_publication
    # The safe cursor does not advance at all: the first day of the
    # pending range (2026-01-02, Friday) is already WAITING_FOR_PUBLICATION.
    assert first_plan.next_cursor == date(2026, 1, 1)

    # Resumption: if the caller persisted `next_cursor` as the new
    # `last_completed_session` for the next run, the waiting session
    # SHALL reappear — never get lost.
    second_plan = planner.plan(
        asset_class=AssetClass.FUND,
        venue="LU-FUNDS",
        mic=None,
        last_completed_session=first_plan.next_cursor,
        today=date(2026, 1, 9),
    )
    assert date(2026, 1, 9) in second_plan.waiting_for_publication
    assert second_plan.next_cursor == date(2026, 1, 1)


def test_lookback_limit_bounds_how_far_back_recovery_reaches() -> None:
    provider = FakeMarketDataProvider()
    planner = RecoveryPlanner(
        provider, RecoveryLimits(max_lookback_days=5, max_sessions_per_chunk=100)
    )

    plan = planner.plan(
        asset_class=AssetClass.EQUITY,
        venue="XETR",
        mic="XETR",
        last_completed_session=None,  # no session was ever completed
        today=date(2026, 1, 20),
    )

    earliest_expected = date(2026, 1, 15)  # today - 5 days
    all_planned_dates = {d for chunk in plan.chunks for d in chunk.session_dates}
    assert all(d >= earliest_expected for d in all_planned_dates)


def test_no_pending_range_produces_empty_plan() -> None:
    provider = FakeMarketDataProvider()
    planner = RecoveryPlanner(provider)

    plan = planner.plan(
        asset_class=AssetClass.CRYPTO,
        venue="KRAKEN",
        mic=None,
        last_completed_session=date(2026, 1, 9),
        today=date(2026, 1, 9),
    )

    # Crypto 24/7: today is already completed, no pending range remains.
    assert plan.chunks == ()
    assert plan.next_cursor == date(2026, 1, 9)


def test_crypto_sessions_never_marked_no_session() -> None:
    provider = FakeMarketDataProvider()
    checks = provider.sessions_in_range(
        asset_class=AssetClass.CRYPTO,
        venue="KRAKEN",
        mic=None,
        start=date(2026, 1, 3),  # Saturday
        end=date(2026, 1, 4),  # Sunday
    )
    assert all(check.expectation is SessionExpectation.EXPECTED_PUBLISHED for check in checks)
