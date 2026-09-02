"""Neutral port for descriptive instrument metadata."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class InstrumentMetadata:
    """Provider-owned descriptive fields, kept separate from identifiers."""

    external_id: str
    name: str | None = None
    ticker: str | None = None
    venue: str | None = None
    currency: str | None = None


class DescriptiveMetadataPort(Protocol):
    """Contract for fetching descriptive fields for one provider identity."""

    def get_metadata(self, external_id: str) -> InstrumentMetadata:
        """Return metadata without treating it as identifier authority."""
        ...
