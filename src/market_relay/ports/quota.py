"""Neutral port for per-source quota.

`specs/market-data-ingestion/spec.md` § "Quotas and partial failures"
requires deferring work when a source exhausts its quota, without
continuing to make useless requests.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class QuotaStatus:
    source: str
    remaining: int
    limit: int
    reset_at: datetime | None = None

    @property
    def exhausted(self) -> bool:
        return self.remaining <= 0


class QuotaPort(Protocol):
    """Contract for querying and consuming per-source quota."""

    def check(self, source: str) -> QuotaStatus:
        """Current quota status, without side effects."""
        ...

    def consume(self, source: str, *, cost: int = 1) -> QuotaStatus:
        """Consumes `cost` units and returns the resulting status.

        An adapter SHALL refuse to consume below zero: once the quota is
        reached, `consume` returns an exhausted status without issuing
        further requests to the provider.
        """
        ...
