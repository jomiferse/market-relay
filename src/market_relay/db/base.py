"""Declarative base and common persistence utilities.

We use an explicit naming convention for constraints because Alembic needs
stable names when generating reversible migrations, especially on SQLite,
where limited ALTER TABLE support forces "batch mode" (recreating the
table) to apply changes reversibly.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Declarative base shared by all ORM models."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def utcnow() -> datetime:
    """Current instant in UTC, with no microseconds ambiguous across dialects."""

    return datetime.now(UTC)


class UUIDPrimaryKeyMixin:
    """Client-generated UUID primary key, portable across dialects."""

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4, sort_order=-1)


class TimestampMixin:
    """Creation and update timestamps in UTC."""

    created_at: Mapped[datetime] = mapped_column(default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow, nullable=False)
