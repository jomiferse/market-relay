"""Policy gate: blocks retrieval and publication without `APPROVED` evidence.

`specs/source-governance/spec.md` requires two independent controls, one
before retrieval and another before responding to a consumer, and prohibits
inferring approval from technical access: the absence of a recorded
decision SHALL be treated as `UNRESOLVED`, never as `APPROVED`.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from market_relay.db.base import utcnow
from market_relay.domain.governance.models import (
    PolicyCapability,
    PolicyStatus,
    SourcePolicyDecision,
)


class PolicyNotAuthorizedError(Exception):
    """One or more required capabilities are not `APPROVED` for the source."""

    def __init__(self, source: str, blocking: Mapping[PolicyCapability, PolicyStatus]) -> None:
        self.source = source
        self.blocking = blocking
        detail = ", ".join(f"{cap.value}={status.value}" for cap, status in blocking.items())
        super().__init__(f"Source '{source}' not authorized: {detail}")


@dataclass(frozen=True, slots=True)
class IngestionAuthorization:
    """Immutable decisions that authorized retrieval and storage."""

    retrieval_decision: SourcePolicyDecision
    storage_decision: SourcePolicyDecision


class PolicyGate:
    """Versioned policy registry and enforcement of access gates."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def record_decision(
        self,
        *,
        source: str,
        capability: PolicyCapability,
        status: PolicyStatus,
        evidence_reference: str,
        reviewed_by: str,
        reviewed_at: datetime | None = None,
        notes: str | None = None,
    ) -> SourcePolicyDecision:
        """Inserts a new version of the decision. Never overwrites an
        existing row: the full history remains for auditing even when the
        new version denies or revokes a previous permission.
        """

        next_version = self._next_version(source, capability)
        decision = SourcePolicyDecision(
            source=source,
            capability=capability,
            version=next_version,
            status=status,
            evidence_reference=evidence_reference,
            reviewed_by=reviewed_by,
            reviewed_at=reviewed_at or utcnow(),
            notes=notes,
        )
        self._session.add(decision)
        self._session.flush()
        return decision

    def _next_version(self, source: str, capability: PolicyCapability) -> int:
        stmt = select(func.max(SourcePolicyDecision.version)).where(
            SourcePolicyDecision.source == source,
            SourcePolicyDecision.capability == capability,
        )
        current_max = self._session.scalar(stmt)
        return 1 if current_max is None else current_max + 1

    def effective_decision(
        self, source: str, capability: PolicyCapability
    ) -> SourcePolicyDecision | None:
        """The effective version (highest `version`) for source and
        capability, or `None` if a decision was never recorded — which is
        treated as `UNRESOLVED` by the rest of the gate.
        """

        stmt = (
            select(SourcePolicyDecision)
            .where(
                SourcePolicyDecision.source == source,
                SourcePolicyDecision.capability == capability,
            )
            .order_by(SourcePolicyDecision.version.desc())
            .limit(1)
        )
        return self._session.scalars(stmt).first()

    def effective_status(self, source: str, capability: PolicyCapability) -> PolicyStatus:
        decision = self.effective_decision(source, capability)
        return decision.status if decision is not None else PolicyStatus.UNRESOLVED

    def require(
        self, source: str, capabilities: Iterable[PolicyCapability]
    ) -> dict[PolicyCapability, PolicyStatus]:
        """Verifies that all the given capabilities are `APPROVED`.

        Raises `PolicyNotAuthorizedError` with the detail of the blocking
        capabilities (`DENIED` or `UNRESOLVED`) otherwise.
        """

        statuses = {cap: self.effective_status(source, cap) for cap in capabilities}
        blocking = {
            cap: status for cap, status in statuses.items() if status != PolicyStatus.APPROVED
        }
        if blocking:
            raise PolicyNotAuthorizedError(source, blocking)
        return statuses

    def authorize_retrieval(self, source: str) -> None:
        """Gate before retrieving data from a source."""

        self.require(source, [PolicyCapability.RETRIEVE])

    def authorize_ingestion(self, source: str) -> IngestionAuthorization:
        """Gate before retrieving AND persisting observations from a source.

        Ingestion requires `RETRIEVE` (technical access) and `STORE`
        (permission to store what was retrieved); both SHALL be `APPROVED`
        before invoking the provider or writing any observation
        (specs/source-governance/spec.md § "Policy-governed activation":
        "prevent ingestion ... when the required permission is denied or
        unresolved"). `RETRIEVE` approved without `STORE` approved is not
        enough: retrieving without permission to store would still violate
        the policy even if the response is never published. This gate is
        distinct from, and stricter than, `authorize_retrieval`, and
        deliberately does not require `DISPLAY` or `REDISTRIBUTE`: that
        publication gate to a consumer is the separate responsibility of
        `authorize_publication` (Wave 4 API).
        """

        self.require(source, [PolicyCapability.RETRIEVE, PolicyCapability.STORE])
        retrieval = self.effective_decision(source, PolicyCapability.RETRIEVE)
        storage = self.effective_decision(source, PolicyCapability.STORE)
        assert retrieval is not None and storage is not None
        return IngestionAuthorization(retrieval_decision=retrieval, storage_decision=storage)

    def is_publication_authorized(self, source: str) -> bool:
        """`True` if `STORE`, `DISPLAY`, and `REDISTRIBUTE` are all three
        `APPROVED` for the source *at this instant*, without raising.

        This is the basis for dynamic revocation of publishability
        (`domain.observations.selection.ObservationSelector`): when a later
        review denies or leaves unresolved any of the three capabilities,
        this function immediately stops returning `True`, without any
        `Observation` row being mutated — the source of truth is the
        versioned history of `SourcePolicyDecision`, never a flag
        materialized on the observation (specs/market-observations/spec.md
        § "Preserved history").
        """

        return all(
            self.effective_status(source, capability) == PolicyStatus.APPROVED
            for capability in (
                PolicyCapability.STORE,
                PolicyCapability.DISPLAY,
                PolicyCapability.REDISTRIBUTE,
            )
        )

    def authorize_publication(self, source: str) -> None:
        """Gate before returning observations from a source to a consumer
        (Holdria or another third party). `STORE`, `DISPLAY`, and
        `REDISTRIBUTE` must all three be `APPROVED`: publishing to a
        consumer implies redistributing the stored data, so a `REDISTRIBUTE`
        that is `UNRESOLVED` or `DENIED` blocks publication even when
        `STORE` and `DISPLAY` are approved (specs/source-governance/spec.md
        § 'API technically accessible without redistribution permission';
        openspec 'Stored data not redistributable'). `APPROVED` is never
        inferred from an absent permission.
        """

        self.require(
            source,
            [
                PolicyCapability.STORE,
                PolicyCapability.DISPLAY,
                PolicyCapability.REDISTRIBUTE,
            ],
        )

    def requires_attribution(self, source: str) -> bool:
        return self.effective_status(source, PolicyCapability.ATTRIBUTE) == PolicyStatus.APPROVED

    def may_retain(self, source: str) -> bool:
        return self.effective_status(source, PolicyCapability.RETAIN) == PolicyStatus.APPROVED
