"""Neutral port for a provider's latest published price."""

from __future__ import annotations

from typing import Protocol

from market_relay.ports.historical import RawObservation


class LatestPricePort(Protocol):
    """Contract for the latest published observation, distinct from history."""

    def fetch_latest(self, *, external_listing_id: str) -> RawObservation | None:
        """Return the latest published observation or no value."""
        ...
