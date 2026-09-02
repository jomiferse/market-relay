"""ORM model for the versioned registry of per-source policies and evidence.

`specs/source-governance/spec.md` requires declaring separately, per source
and use, whether `retrieve`, `store`, `display`, `redistribute`,
`attribute`, and `retain` are permitted, keeping evidence, review date, and
`APPROVED`/`DENIED`/`UNRESOLVED` status — never inferred from technical
access. Each decision is inserted as a new version; an existing row is
never overwritten, so the audit history is preserved intact even when a
later review denies or revokes a previously granted permission.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import Enum, String, UniqueConstraint, event
from sqlalchemy.orm import Mapped, mapped_column

from market_relay.db.base import Base, UUIDPrimaryKeyMixin, utcnow


class PolicyCapability(StrEnum):
    """Independent permissions that a source can grant or deny."""

    RETRIEVE = "RETRIEVE"
    STORE = "STORE"
    DISPLAY = "DISPLAY"
    REDISTRIBUTE = "REDISTRIBUTE"
    ATTRIBUTE = "ATTRIBUTE"
    RETAIN = "RETAIN"


class PolicyStatus(StrEnum):
    """Status of the policy decision. `APPROVED` is never inferred."""

    APPROVED = "APPROVED"
    DENIED = "DENIED"
    UNRESOLVED = "UNRESOLVED"


class PolicyDecisionImmutableError(Exception):
    """A persisted policy decision cannot be changed or deleted."""


class SourcePolicyDecision(UUIDPrimaryKeyMixin, Base):
    """An immutable version of a source's policy decision for a specific
    capability. The *effective* policy for a source/capability is the row
    with the highest `version`; earlier ones remain for auditing.
    """

    __tablename__ = "source_policy_decisions"
    __table_args__ = (
        UniqueConstraint(
            "source", "capability", "version", name="uq_source_policy_source_cap_version"
        ),
    )

    source: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    capability: Mapped[PolicyCapability] = mapped_column(
        Enum(PolicyCapability, native_enum=False, length=16, validate_strings=True),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[PolicyStatus] = mapped_column(
        Enum(PolicyStatus, native_enum=False, length=16, validate_strings=True), nullable=False
    )
    # Reference to the evidence (URL, document path, ticket) — never a
    # secret or credential.
    evidence_reference: Mapped[str] = mapped_column(String(512), nullable=False)
    reviewed_by: Mapped[str] = mapped_column(String(128), nullable=False)
    reviewed_at: Mapped[datetime] = mapped_column(nullable=False)
    notes: Mapped[str | None] = mapped_column(String(1024))
    created_at: Mapped[datetime] = mapped_column(default=utcnow, nullable=False)


@event.listens_for(SourcePolicyDecision, "before_update")
def _reject_policy_update(mapper: object, connection: object, target: SourcePolicyDecision) -> None:
    raise PolicyDecisionImmutableError(
        f"Policy decision {target.id} is append-only: UPDATE not allowed."
    )


@event.listens_for(SourcePolicyDecision, "before_delete")
def _reject_policy_delete(mapper: object, connection: object, target: SourcePolicyDecision) -> None:
    raise PolicyDecisionImmutableError(
        f"Policy decision {target.id} is append-only: DELETE not allowed."
    )
