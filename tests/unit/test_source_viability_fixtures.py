"""Validates the shape of the reproducible source-viability fixtures
(tasks.md 3.1-3.4; docs/source-viability/). These files are the
canonical data source for wave 2's documentation: if a fixture is
malformed or a global status becomes inconsistent with its capabilities,
these tests SHALL fail before the documentation is considered valid.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "source_viability"

VALID_STATUSES = {"GO", "NO-GO", "UNRESOLVED"}
REQUIRED_CAPABILITIES = {"RETRIEVE", "STORE", "DISPLAY", "REDISTRIBUTE", "ATTRIBUTE", "RETAIN"}
VALID_ASSET_CLASSES = {"EQUITY", "ETF", "FUND", "CRYPTO"}


def _load(name: str) -> Any:
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


def _global_status_for(capabilities: dict[str, dict[str, str]]) -> str:
    """Same aggregation rule described in docs/source-viability/README.md:
    NO-GO if any capability is NO-GO, else UNRESOLVED if any capability is,
    else GO.
    """

    statuses = {c["status"] for c in capabilities.values()}
    if "NO-GO" in statuses:
        return "NO-GO"
    if "UNRESOLVED" in statuses:
        return "UNRESOLVED"
    return "GO"


@pytest.fixture(scope="module")
def decisions() -> Any:
    return _load("source_decisions.json")


@pytest.fixture(scope="module")
def matrix() -> Any:
    return _load("instrument_matrix.json")


# -- source_decisions.json ----------------------------------------------------


def test_decisions_top_level_shape(decisions: Any) -> None:
    assert isinstance(decisions["sources"], list)
    assert len(decisions["sources"]) > 0


def test_decisions_source_ids_are_unique(decisions: Any) -> None:
    ids = [source["source_id"] for source in decisions["sources"]]
    assert len(ids) == len(set(ids))


def test_decisions_every_source_declares_all_capabilities(decisions: Any) -> None:
    for source in decisions["sources"]:
        assert set(source["capabilities"].keys()) == REQUIRED_CAPABILITIES, source["source_id"]


def test_decisions_every_capability_status_is_valid(decisions: Any) -> None:
    for source in decisions["sources"]:
        for capability, decision in source["capabilities"].items():
            assert decision["status"] in VALID_STATUSES, f"{source['source_id']}.{capability}"
            # The evidence SHALL be a public URL, never an empty value.
            assert decision["evidence"].startswith("http")


def test_decisions_global_status_matches_worst_capability(decisions: Any) -> None:
    """The documented 'global_status' SHALL be consistent with the worst
    individual capability: a global GO is never presented if any
    required capability is NO-GO or UNRESOLVED.
    """

    for source in decisions["sources"]:
        expected = _global_status_for(source["capabilities"])
        assert source["global_status"] == expected, source["source_id"]


def test_decisions_no_source_is_globally_go_except_documented_identity_case(
    decisions: Any,
) -> None:
    """tasks.md 3.3/3.4 requires that no price provider or scraper be left
    'GO' without solid evidence; in this review only OpenFIGI (identity,
    not prices) reaches GO. A future change that adds a new GO to this
    fixture SHALL explicitly review whether it should be enabled as a real
    adapter, not just update this test.
    """

    go_sources = {f["source_id"] for f in decisions["sources"] if f["global_status"] == "GO"}
    assert go_sources == {"openfigi"}


def test_openfigi_go_is_scoped_to_the_figi_identifier_only(decisions: Any) -> None:
    """OpenFIGI's ToS (https://www.openfigi.com/docs/terms-of-service)
    only grants an explicit public-domain dedication — not an MIT
    license — over the FIGI Identifier in its §1; the 'Related Security
    Descriptions' (ticker, name, exchCode, marketSector, securityType)
    only appear in the disclaimer clause of §3, with no equivalent grant
    of rights. The fixture SHALL reflect that strictly FIGI-only scope
    and never assert an MIT license.
    """

    openfigi = next(f for f in decisions["sources"] if f["source_id"] == "openfigi")

    blob = json.dumps(openfigi, ensure_ascii=False)
    assert "MIT" not in blob, "must not describe the public-domain dedication as an MIT license"
    assert "allowlist" in openfigi["scope_limitation"].lower()
    assert "figi" in openfigi["scope_limitation"].lower()
    assert "UNRESOLVED" in openfigi["scope_limitation"]

    # No capability should unconditionally assert that it authorizes
    # ticker/name/exchCode/securityType: REDISTRIBUTE (the most sensitive
    # permission) must make explicit that it is limited to the FIGI Identifier.
    redistribute_note = openfigi["capabilities"]["REDISTRIBUTE"]["note"]
    assert "FIGI Identifiers" in redistribute_note
    assert "Related Security Descriptions" in redistribute_note


# -- instrument_matrix.json ----------------------------------------------------


def test_matrix_top_level_shape(matrix: Any) -> None:
    assert isinstance(matrix["instruments"], list)
    assert len(matrix["instruments"]) > 0


def test_matrix_instrument_ids_are_unique(matrix: Any) -> None:
    ids = [i["id"] for i in matrix["instruments"]]
    assert len(ids) == len(set(ids))


def test_matrix_covers_required_asset_classes(matrix: Any) -> None:
    """Task 3.1 requires Xetra and Euronext equities, UCITS ETFs, European
    funds, and EUR crypto assets: all MVP asset classes
    (specs/instrument-catalog) SHALL be represented.
    """

    classes = {i["asset_class"] for i in matrix["instruments"]}
    assert classes == VALID_ASSET_CLASSES


def test_matrix_covers_xetra_and_euronext_venues(matrix: Any) -> None:
    venues = {i["venue"] for i in matrix["instruments"] if i["venue"]}
    assert any("Xetra" in v for v in venues)
    assert any("Euronext" in v for v in venues)


def test_matrix_every_instrument_declares_currency(matrix: Any) -> None:
    for instrument in matrix["instruments"]:
        assert instrument["currency"] == "EUR", instrument["id"]


def test_matrix_every_instrument_documents_missing_sessions_and_anomalies(matrix: Any) -> None:
    for instrument in matrix["instruments"]:
        assert instrument["expected_missing_sessions"], instrument["id"]
        assert isinstance(instrument["known_anomalies"], list)
        assert len(instrument["known_anomalies"]) > 0, instrument["id"]


def test_matrix_figi_is_never_prefilled(matrix: Any) -> None:
    """FIGI SHALL be resolved at runtime via OpenFIGI, not fixed as a
    value unverified by this documentary review
    (docs/source-viability/openfigi-evaluation.md).
    """

    for instrument in matrix["instruments"]:
        assert instrument["figi"] is None, instrument["id"]


_ISIN_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")


def test_matrix_fund_rows_have_real_verifiable_isins(matrix: Any) -> None:
    """tasks.md 3.1 requires real unlisted European funds, with an ISIN
    verified against a primary document from the management company
    (KIID/factsheet/prospectus) — never a placeholder like
    'EXAMPLE-UNVERIFIED'. specs/instrument-catalog already allows
    missing MIC/ticker for instruments not listed on an exchange: an
    unlisted fund SHALL leave them empty, never fabricate them.
    """

    funds = [i for i in matrix["instruments"] if i["asset_class"] == "FUND"]
    assert len(funds) >= 2, "expected at least two real unlisted European funds"

    isins = [f["isin"] for f in funds]
    assert len(isins) == len(set(isins)), "duplicate fund ISIN"

    for fund in funds:
        assert fund["isin"] != "EXAMPLE-UNVERIFIED", fund["id"]
        assert _ISIN_RE.match(fund["isin"]), f"{fund['id']}: ISIN has an invalid shape"
        assert fund["mic"] is None, fund["id"]
        assert fund["ticker"] is None, fund["id"]


def test_matrix_crypto_instruments_have_no_isin_or_mic(matrix: Any) -> None:
    """specs/instrument-catalog § 'Crypto asset without ISIN or MIC'."""

    for instrument in matrix["instruments"]:
        if instrument["asset_class"] == "CRYPTO":
            assert instrument["isin"] is None
            assert instrument["mic"] is None
