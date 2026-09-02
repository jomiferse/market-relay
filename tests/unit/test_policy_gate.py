"""Policy gate: APPROVED/DENIED/UNRESOLVED blocks retrieval and
publication (tasks.md 2.2; specs/source-governance/spec.md).
"""

from __future__ import annotations

import pytest

from market_relay.domain.governance import (
    PolicyCapability,
    PolicyGate,
    PolicyNotAuthorizedError,
    PolicyStatus,
)


def test_unresolved_capability_blocks_retrieval_by_default(db_session) -> None:
    """No recorded decision SHALL be treated as UNRESOLVED, never
    as APPROVED (approval of technical access is never inferred).
    """

    gate = PolicyGate(db_session)

    assert gate.effective_status("acme-source", PolicyCapability.RETRIEVE) is (
        PolicyStatus.UNRESOLVED
    )
    with pytest.raises(PolicyNotAuthorizedError):
        gate.authorize_retrieval("acme-source")


def _approve(gate: PolicyGate, source: str, capability: PolicyCapability) -> None:
    gate.record_decision(
        source=source,
        capability=capability,
        status=PolicyStatus.APPROVED,
        evidence_reference=f"https://{source}.example/terms#{capability.value.lower()}",
        reviewed_by="ops@holdria.test",
    )


def test_unresolved_redistribution_blocks_publication_scenario(db_session) -> None:
    """specs/source-governance/spec.md § 'API technically accessible without
    redistribution permission'; consumer-api § 'Stored data not
    redistributable'. `REDISTRIBUTE` in `UNRESOLVED` SHALL block
    publication to Holdria/consumer even with `STORE` and `DISPLAY`
    approved: redistribution approval is never inferred.
    """

    gate = PolicyGate(db_session)
    _approve(gate, "acme-source", PolicyCapability.RETRIEVE)
    _approve(gate, "acme-source", PolicyCapability.STORE)
    _approve(gate, "acme-source", PolicyCapability.DISPLAY)
    gate.record_decision(
        source="acme-source",
        capability=PolicyCapability.REDISTRIBUTE,
        status=PolicyStatus.UNRESOLVED,
        evidence_reference="https://acme.example/terms#redistribute",
        reviewed_by="ops@holdria.test",
    )

    # Retrieval allowed...
    gate.authorize_retrieval("acme-source")
    # ...but publication to the consumer SHALL remain blocked while
    # REDISTRIBUTE is not APPROVED, even if STORE and DISPLAY are.
    with pytest.raises(PolicyNotAuthorizedError) as exc_info:
        gate.authorize_publication("acme-source")
    assert PolicyCapability.REDISTRIBUTE in exc_info.value.blocking


def test_denied_redistribution_blocks_publication(db_session) -> None:
    """A `REDISTRIBUTE` explicitly `DENIED` blocks publication
    just like `UNRESOLVED`, even with `STORE` and `DISPLAY` approved.
    """

    gate = PolicyGate(db_session)
    _approve(gate, "acme-source", PolicyCapability.STORE)
    _approve(gate, "acme-source", PolicyCapability.DISPLAY)
    gate.record_decision(
        source="acme-source",
        capability=PolicyCapability.REDISTRIBUTE,
        status=PolicyStatus.DENIED,
        evidence_reference="https://acme.example/terms#redistribute",
        reviewed_by="ops@holdria.test",
    )

    with pytest.raises(PolicyNotAuthorizedError) as exc_info:
        gate.authorize_publication("acme-source")
    assert exc_info.value.blocking[PolicyCapability.REDISTRIBUTE] == PolicyStatus.DENIED


def test_publication_succeeds_only_with_store_display_and_redistribute_approved(
    db_session,
) -> None:
    """`authorize_publication` only allows publishing to Holdria/consumer
    when `STORE`, `DISPLAY` and `REDISTRIBUTE` are all three `APPROVED`.
    """

    gate = PolicyGate(db_session)
    _approve(gate, "acme-source", PolicyCapability.STORE)
    _approve(gate, "acme-source", PolicyCapability.DISPLAY)
    _approve(gate, "acme-source", PolicyCapability.REDISTRIBUTE)

    gate.authorize_publication("acme-source")  # does not raise


def test_ingestion_requires_both_retrieve_and_store(db_session) -> None:
    """Ingestion SHALL require `RETRIEVE` *and* `STORE`: retrieving without
    permission to store would still violate policy even if the response
    never gets published (specs/source-governance/spec.md
    § "Policy-governed activation").
    """

    gate = PolicyGate(db_session)
    _approve(gate, "acme-source", PolicyCapability.RETRIEVE)
    # STORE stays UNRESOLVED (never recorded): ingestion SHALL block
    # both the fetch and the persistence, not just publication.
    with pytest.raises(PolicyNotAuthorizedError) as exc_info:
        gate.authorize_ingestion("acme-source")
    assert PolicyCapability.STORE in exc_info.value.blocking
    # RETRIEVE alone still allows the looser retrieval gate.
    gate.authorize_retrieval("acme-source")


def test_ingestion_denied_store_blocks_even_with_retrieve_approved(db_session) -> None:
    gate = PolicyGate(db_session)
    _approve(gate, "acme-source", PolicyCapability.RETRIEVE)
    gate.record_decision(
        source="acme-source",
        capability=PolicyCapability.STORE,
        status=PolicyStatus.DENIED,
        evidence_reference="https://acme.example/terms#store",
        reviewed_by="ops@holdria.test",
    )

    with pytest.raises(PolicyNotAuthorizedError) as exc_info:
        gate.authorize_ingestion("acme-source")
    assert exc_info.value.blocking[PolicyCapability.STORE] == PolicyStatus.DENIED


def test_ingestion_succeeds_with_only_retrieve_and_store_approved(db_session) -> None:
    """`authorize_ingestion` does not require `DISPLAY` or `REDISTRIBUTE`:
    that consumer-publication gate is a separate responsibility of
    `authorize_publication` (Wave 4 API).
    """

    gate = PolicyGate(db_session)
    _approve(gate, "acme-source", PolicyCapability.RETRIEVE)
    _approve(gate, "acme-source", PolicyCapability.STORE)

    gate.authorize_ingestion("acme-source")  # does not raise

    with pytest.raises(PolicyNotAuthorizedError):
        gate.authorize_publication("acme-source")


def test_is_publication_authorized_reflects_current_policy_without_raising(db_session) -> None:
    gate = PolicyGate(db_session)
    assert gate.is_publication_authorized("acme-source") is False

    _approve(gate, "acme-source", PolicyCapability.STORE)
    _approve(gate, "acme-source", PolicyCapability.DISPLAY)
    _approve(gate, "acme-source", PolicyCapability.REDISTRIBUTE)
    assert gate.is_publication_authorized("acme-source") is True

    # A later revocation (new DENIED version) is reflected immediately.
    gate.record_decision(
        source="acme-source",
        capability=PolicyCapability.REDISTRIBUTE,
        status=PolicyStatus.DENIED,
        evidence_reference="https://acme.example/terms/v2#redistribute",
        reviewed_by="ops@holdria.test",
    )
    assert gate.is_publication_authorized("acme-source") is False


def test_approved_source_requiring_attribution_is_flagged(db_session) -> None:
    """specs/source-governance/spec.md § 'Approved source requiring attribution'."""

    gate = PolicyGate(db_session)
    gate.record_decision(
        source="attributed-source",
        capability=PolicyCapability.ATTRIBUTE,
        status=PolicyStatus.APPROVED,
        evidence_reference="https://attributed.example/terms#attribution",
        reviewed_by="ops@holdria.test",
    )

    assert gate.requires_attribution("attributed-source") is True
    assert gate.requires_attribution("acme-source") is False


def test_revised_policy_downgrade_stops_new_access_but_keeps_audit_trail(db_session) -> None:
    """specs/source-governance/spec.md § 'Modified conditions': a
    revision to DENIED/UNRESOLVED stops new access without erasing history.
    """

    gate = PolicyGate(db_session)
    first = gate.record_decision(
        source="revocable-source",
        capability=PolicyCapability.RETRIEVE,
        status=PolicyStatus.APPROVED,
        evidence_reference="https://revocable.example/terms/v1",
        reviewed_by="ops@holdria.test",
    )
    gate.authorize_retrieval("revocable-source")  # allowed under v1

    second = gate.record_decision(
        source="revocable-source",
        capability=PolicyCapability.RETRIEVE,
        status=PolicyStatus.DENIED,
        evidence_reference="https://revocable.example/terms/v2",
        reviewed_by="ops@holdria.test",
    )

    with pytest.raises(PolicyNotAuthorizedError):
        gate.authorize_retrieval("revocable-source")

    assert second.version == first.version + 1
    # The audit trail remains: both versions are still readable.
    effective = gate.effective_decision("revocable-source", PolicyCapability.RETRIEVE)
    assert effective is not None
    assert effective.version == second.version
    from sqlalchemy import select

    from market_relay.domain.governance.models import SourcePolicyDecision

    all_versions = db_session.scalars(
        select(SourcePolicyDecision).where(SourcePolicyDecision.source == "revocable-source")
    ).all()
    assert {d.version for d in all_versions} == {1, 2}
