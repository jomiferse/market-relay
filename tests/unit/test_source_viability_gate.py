"""Verifies that the documentary evaluation of sources (tasks.md 3.1-3.4)
does not, by itself, enable any real source: neither in default
configuration nor as an implicit `APPROVED` decision in the policy record.

A `GO` conclusion in docs/source-viability/ identifies a candidate source
for a future explicit implementation task; it must not translate into real
access without a policy decision deliberately registered by the
operational process described in specs/source-governance/spec.md.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from market_relay.config.settings import Settings
from market_relay.domain.governance import PolicyCapability, PolicyGate, PolicyStatus

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "source_viability"


def _researched_source_ids() -> list[str]:
    data: Any = json.loads((FIXTURES_DIR / "source_decisions.json").read_text(encoding="utf-8"))
    return [source["source_id"] for source in data["sources"]]


def test_default_settings_enable_only_fake() -> None:
    settings = Settings(_env_file=None)

    assert settings.enabled_sources == ("fake",)
    for source_id in _researched_source_ids():
        assert source_id not in settings.enabled_sources


def test_no_researched_source_has_an_approved_policy_decision(db_session) -> None:
    """No source evaluated in this documentary wave — including 'openfigi',
    with a documentary GO verdict — has an APPROVED SourcePolicyDecision
    seeded in the schema. Enabling a real source requires a deliberate,
    auditable record, not a side effect of documentation.
    """

    gate = PolicyGate(db_session)

    for source_id in _researched_source_ids():
        for capability in PolicyCapability:
            assert gate.effective_status(source_id, capability) is PolicyStatus.UNRESOLVED, (
                f"{source_id}.{capability}"
            )


def test_openfigi_go_verdict_does_not_imply_runtime_authorization(db_session) -> None:
    """Explicit case: even though openfigi-evaluation.md concludes GO, that
    alone MUST NOT authorize retrieval or publication without a registered
    policy decision — the same default behavior as any source with no
    decision (tests/unit/test_policy_gate.py).
    """

    from market_relay.domain.governance import PolicyNotAuthorizedError

    gate = PolicyGate(db_session)

    try:
        gate.authorize_retrieval("openfigi")
    except PolicyNotAuthorizedError as exc:
        assert PolicyCapability.RETRIEVE in exc.blocking
    else:
        raise AssertionError("expected PolicyNotAuthorizedError for 'openfigi' with no decision")
