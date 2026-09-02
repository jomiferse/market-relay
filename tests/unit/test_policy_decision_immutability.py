"""Acquisition policy references point to immutable decision records."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from market_relay.domain.governance.models import PolicyCapability, PolicyStatus
from market_relay.domain.governance.policy_gate import PolicyGate


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE source_policy_decisions SET status='DENIED' WHERE id=:id",
        "DELETE FROM source_policy_decisions WHERE id=:id",
    ],
)
def test_sqlite_rejects_policy_decision_update_and_delete(db_session, statement: str) -> None:
    decision = PolicyGate(db_session).record_decision(
        source="fake",
        capability=PolicyCapability.RETRIEVE,
        status=PolicyStatus.APPROVED,
        evidence_reference="internal:test-only",
        reviewed_by="test-suite",
        reviewed_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    db_session.commit()

    with pytest.raises(DBAPIError):
        db_session.execute(text(statement), {"id": decision.id})
        db_session.commit()
    db_session.rollback()

    preserved = PolicyGate(db_session).effective_decision("fake", PolicyCapability.RETRIEVE)
    assert preserved is not None
    assert preserved.id == decision.id
    assert preserved.status == PolicyStatus.APPROVED
