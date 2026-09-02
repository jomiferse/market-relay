"""Capability-specific adapters and canonical-listing calendar routes.

Registration only makes code addressable. Settings and policy decisions
independently control activation and authorization.
"""

from __future__ import annotations

from collections.abc import Iterator, MutableMapping
from typing import Any

from market_relay.adapters.fake.provider import SOURCE_NAME as FAKE_SOURCE_NAME
from market_relay.adapters.fake.provider import FakeMarketDataProvider
from market_relay.ports.calendar import MarketCalendarPort
from market_relay.ports.discovery import DiscoveryPort
from market_relay.ports.historical import HistoricalPricePort
from market_relay.ports.latest import LatestPricePort
from market_relay.ports.metadata import DescriptiveMetadataPort
from market_relay.ports.quota import QuotaPort


class UnknownSourceError(Exception):
    """An adapter was requested for a source that is not registered."""


class CalendarUnavailableError(Exception):
    """No calendar is registered for a canonical listing route."""


_FAKE = FakeMarketDataProvider()
_DISCOVERY_ADAPTERS: dict[str, DiscoveryPort] = {FAKE_SOURCE_NAME: _FAKE}
_METADATA_ADAPTERS: dict[str, DescriptiveMetadataPort] = {}
_HISTORICAL_ADAPTERS: dict[str, HistoricalPricePort] = {FAKE_SOURCE_NAME: _FAKE}
_LATEST_ADAPTERS: dict[str, LatestPricePort] = {}
_CALENDAR_ADAPTERS: dict[str, MarketCalendarPort] = {FAKE_SOURCE_NAME: _FAKE}
_QUOTA_ADAPTERS: dict[str, QuotaPort] = {FAKE_SOURCE_NAME: _FAKE}

# MIC first, venue second, and an explicit local fallback last. Price source
# priority never participates in this lookup.
_CALENDAR_ROUTES: dict[str, str] = {"*": FAKE_SOURCE_NAME}


class _CapabilityRegistrationView(MutableMapping[str, Any]):
    """Compatibility view that registers only methods an object provides."""

    def __getitem__(self, key: str) -> Any:
        for registry in (
            _HISTORICAL_ADAPTERS,
            _DISCOVERY_ADAPTERS,
            _CALENDAR_ADAPTERS,
            _QUOTA_ADAPTERS,
        ):
            if key in registry:
                return registry[key]
        raise KeyError(key)

    def __setitem__(self, key: str, value: Any) -> None:
        capabilities = (
            ("search", _DISCOVERY_ADAPTERS),
            ("get_metadata", _METADATA_ADAPTERS),
            ("fetch_range", _HISTORICAL_ADAPTERS),
            ("fetch_latest", _LATEST_ADAPTERS),
            ("sessions_in_range", _CALENDAR_ADAPTERS),
        )
        for method, registry in capabilities:
            if hasattr(value, method):
                registry[key] = value
        if hasattr(value, "check") and hasattr(value, "consume"):
            _QUOTA_ADAPTERS[key] = value

    def __delitem__(self, key: str) -> None:
        found = False
        for registry in (
            _DISCOVERY_ADAPTERS,
            _METADATA_ADAPTERS,
            _HISTORICAL_ADAPTERS,
            _LATEST_ADAPTERS,
            _CALENDAR_ADAPTERS,
            _QUOTA_ADAPTERS,
        ):
            found = registry.pop(key, None) is not None or found
        if not found:
            raise KeyError(key)

    def __iter__(self) -> Iterator[str]:
        keys: set[str] = set()
        for registry in (_DISCOVERY_ADAPTERS, _HISTORICAL_ADAPTERS, _CALENDAR_ADAPTERS):
            keys.update(registry)
        return iter(keys)

    def __len__(self) -> int:
        return len(set(iter(self)))


# Existing tests and local extensions may register an object through this view;
# unlike the former registry, it does not require the object to implement every
# capability and runtime code never retrieves a combined adapter from it.
_ADAPTERS: MutableMapping[str, Any] = _CapabilityRegistrationView()


def _get[T](registry: dict[str, T], source: str, capability: str) -> T:
    try:
        return registry[source]
    except KeyError as exc:
        raise UnknownSourceError(
            f"Source '{source}' has no registered {capability} capability."
        ) from exc


def get_discovery_port(source: str) -> DiscoveryPort:
    return _get(_DISCOVERY_ADAPTERS, source, "discovery")


def get_metadata_port(source: str) -> DescriptiveMetadataPort:
    return _get(_METADATA_ADAPTERS, source, "descriptive metadata")


def get_historical_price_port(source: str) -> HistoricalPricePort:
    return _get(_HISTORICAL_ADAPTERS, source, "historical EOD")


def get_latest_price_port(source: str) -> LatestPricePort:
    return _get(_LATEST_ADAPTERS, source, "latest price")


def get_quota_port(source: str) -> QuotaPort:
    return _get(_QUOTA_ADAPTERS, source, "quota")


def get_calendar_port(source: str) -> MarketCalendarPort:
    """Calendar adapter for the given source.

    Raises `UnknownSourceError` if `source` has no registered adapter;
    never infers or fabricates a calendar for an unknown source.
    """

    return _get(_CALENDAR_ADAPTERS, source, "calendar")


def get_calendar_for_listing(*, mic: str | None, venue: str) -> MarketCalendarPort:
    """Resolve a calendar from listing identity, independent of price order."""

    route_keys = [key for key in ((mic or "").upper(), venue.upper(), "*") if key]
    for key in route_keys:
        source = _CALENDAR_ROUTES.get(key)
        if source is not None:
            return get_calendar_port(source)
    raise CalendarUnavailableError(
        f"No calendar is configured for MIC '{mic or ''}' and venue '{venue}'."
    )
