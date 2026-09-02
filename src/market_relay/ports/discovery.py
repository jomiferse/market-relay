"""Neutral port for instrument identity discovery.

No concrete provider (e.g. OpenFIGI) is a universal authority (design.md §
"Hexagonal architecture with governed adapters"): this port defines the
contract any identity adapter must fulfill, without coupling the core to a
provider.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from market_relay.domain.catalog.models import AssetClass


@dataclass(frozen=True, slots=True)
class DiscoveryQuery:
    """Identity search criteria, all optional except `query`."""

    query: str
    asset_class: AssetClass | None = None
    currency: str | None = None
    mic: str | None = None


@dataclass(frozen=True, slots=True)
class DiscoveredIdentity:
    """Candidate returned by a discovery adapter.

    Represents a single candidate listing, never a merge of several;
    ambiguity resolution happens in `CatalogService`, not here.
    """

    source: str
    external_id: str
    name: str
    asset_class: AssetClass
    ticker: str
    venue: str
    currency: str
    isin: str | None = None
    mic: str | None = None


class DiscoveryPort(Protocol):
    """Contract every identity discovery adapter implements."""

    def search(self, query: DiscoveryQuery) -> list[DiscoveredIdentity]:
        """Returns all candidates that satisfy the criteria, without
        choosing one on behalf of the caller.
        """
        ...
