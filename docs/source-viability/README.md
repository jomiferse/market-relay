# Source Viability — MarketRelay

This directory documents section 3 ("Source Viability") of
`openspec/changes/build-market-data-hub/tasks.md`: a technical and
legal review, with public evidence, of the candidate sources for identity and
prices before considering the implementation of any real adapter.

**Scope of this wave.** These documents are for evaluation only.
They do not enable any external source, do not seed `APPROVED` decisions in the
policy registry (`SourcePolicyDecision`), and do not modify
`Settings.enabled_sources`, which remains `("fake",)` — see
`tests/unit/test_source_viability_gate.py`. A documentary `GO`
conclusion identifies a candidate source for a future implementation task; it does not
by itself authorize production access. Enabling a real source
requires, in addition to this document, recording the corresponding decision in
`SourcePolicyDecision` through the operational process described in
`specs/source-governance/spec.md`, with its own review date and
reviewer.

**Guiding principle.** Technical access to an API or page is never
interpreted as permission. When public evidence about storage,
display, redistribution, attribution, or retention is insufficient or
ambiguous, the source is marked `UNRESOLVED` and remains disabled — `APPROVED`
is never assumed by default (the same principle applied in
`PolicyGate.effective_status`, see `src/market_relay/domain/governance/policy_gate.py`).

## Documents

| Document | Task | Content |
|---|---|---|
| [`instrument-matrix.md`](./instrument-matrix.md) | 3.1 | Reproducible matrix of representative instruments (Xetra, Euronext, UCITS ETF, European fund, crypto/EUR) with identifiers, raw `close` semantics, ranges, missing sessions, quotas, and known anomalies. |
| [`openfigi-evaluation.md`](./openfigi-evaluation.md) | 3.2 | Technical and legal evaluation of OpenFIGI as an identity source. |
| [`price-providers-evaluation.md`](./price-providers-evaluation.md) | 3.3 | Evaluation of free price providers by asset class. |
| [`scraping-evaluation.md`](./scraping-evaluation.md) | 3.4 | Evaluation of scraping candidates via published terms and `robots.txt`. |

## Reproducible data

The structured data backing these documents lives in
`tests/fixtures/source_viability/`:

- `instrument_matrix.json` — the same instruments described in
  `instrument-matrix.md`, in machine format.
- `source_decisions.json` — a `GO`/`NO-GO`/`UNRESOLVED` decision per
  source and capability (`RETRIEVE`, `STORE`, `DISPLAY`, `REDISTRIBUTE`,
  `ATTRIBUTE`, `RETAIN`), with the public evidence URL consulted.

`tests/unit/test_source_viability_fixtures.py` verifies that both files
have a valid shape and that the overall status of each source is consistent
with its individual capabilities; `tests/security/test_no_credentials_in_viability_docs.py`
verifies that neither these documents nor those fixtures contain credentials;
`tests/unit/test_source_viability_gate.py` verifies that no source
evaluated here is left enabled by default or with an `APPROVED` decision seeded
in the policy registry.

## Methodology

For each candidate source, public and, where possible,
primary evidence was sought: official API documentation, general or
terms of service conditions, `robots.txt`, and data licensing
pages. Only public links are recorded as evidence — never a
credential nor a test value. When two secondary sources
disagreed or the full text of a legal condition
could not be confirmed within the scope of this review, the
corresponding capability was marked `UNRESOLVED` instead of assuming a favorable
permission.

Date of this review: **2026-09-02**. Review recommended before:
**2027-03-02**, or sooner if any of the sources changes its published
terms.
