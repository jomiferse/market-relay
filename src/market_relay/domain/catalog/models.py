"""Catalog ORM models: instrument, listing, and external identity.

`specs/instrument-catalog/spec.md` requires representing the economic
instrument and its listings separately, without assuming that an ISIN
identifies a single listing, and supporting asset classes (crypto) without
ISIN or MIC.
"""

from __future__ import annotations

import uuid
from datetime import date
from enum import StrEnum

from sqlalchemy import CheckConstraint, Date, Enum, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from market_relay.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class AssetClass(StrEnum):
    """Asset classes supported in the MVP (proposal.md § What Changes)."""

    EQUITY = "EQUITY"
    ETF = "ETF"
    FUND = "FUND"
    CRYPTO = "CRYPTO"


class Instrument(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Canonical economic identity, independent of the listing venue."""

    __tablename__ = "instruments"
    __table_args__ = (UniqueConstraint("isin", name="uq_instruments_isin"),)

    asset_class: Mapped[AssetClass] = mapped_column(
        Enum(AssetClass, native_enum=False, length=16, validate_strings=True), nullable=False
    )
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    # ISIN is optional: crypto assets have no ISIN (specs/instrument-catalog).
    isin: Mapped[str | None] = mapped_column(String(12))
    # FIGI is an identity candidate (design.md), also optional.
    figi: Mapped[str | None] = mapped_column(String(12))

    listings: Mapped[list[Listing]] = relationship(
        back_populates="instrument", cascade="all, delete-orphan"
    )


class Listing(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A specific listing of an instrument: venue, ticker, and currency."""

    __tablename__ = "listings"
    __table_args__ = (
        # The same instrument cannot repeat venue+ticker+currency.
        UniqueConstraint(
            "instrument_id", "venue", "ticker", "currency", name="uq_listings_venue_ticker_ccy"
        ),
    )

    instrument_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("instruments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # MIC (ISO 10383) only applies to regulated markets; crypto has no MIC
    # and uses `venue` as the identifier for the listing venue.
    mic: Mapped[str | None] = mapped_column(String(4))
    venue: Mapped[str] = mapped_column(String(64), nullable=False)
    ticker: Mapped[str] = mapped_column(String(32), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)

    instrument: Mapped[Instrument] = relationship(back_populates="listings")
    external_identities: Mapped[list[ExternalIdentity]] = relationship(
        back_populates="listing", cascade="all, delete-orphan"
    )


class ExternalIdentity(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Traceable correspondence between a listing and a provider identifier,
    with provenance and validity period (design.md § "Separate instrument,
    listing, external identity, and observation").
    """

    __tablename__ = "external_identities"
    __table_args__ = (
        UniqueConstraint(
            "source", "external_id", "valid_from", name="uq_external_identities_source_ext_from"
        ),
        CheckConstraint(
            "valid_to IS NULL OR valid_to >= valid_from",
            name="valid_to_after_valid_from",
        ),
    )

    listing_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("listings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Source that issues the identifier (e.g. "openfigi", "fake").
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    external_id: Mapped[str] = mapped_column(String(128), nullable=False)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date | None] = mapped_column(Date)

    listing: Mapped[Listing] = relationship(back_populates="external_identities")
