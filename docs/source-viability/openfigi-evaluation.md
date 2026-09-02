# Evaluation of OpenFIGI as an identity source (tasks.md 3.2)

**Verdict: `GO`, strictly scoped to the FIGI identifier itself**
(FIGI-only projection/adapter). The non-proprietary descriptive metadata
that the same API returns (security name, ticker, `exchCode`, `marketSector`,
`securityType` — "Related Security Descriptions") **remains `UNRESOLVED`**:
see "Explicit scope limit" below. Review date: 2026-09-02.
Next review recommended: 2027-03-02 or sooner if OpenFIGI/Bloomberg
changes its published terms.

Structured data: [`tests/fixtures/source_viability/source_decisions.json`](../../tests/fixtures/source_viability/source_decisions.json) → `source_id: "openfigi"`.

## Technical viability

- Public, documented mapping API at <https://www.openfigi.com/api/documentation>.
- Rate limits: without a key, 25 requests/min (max 10 items per
  request); with a free key, 25 requests/6s (max 100 items per
  request) — no documented monthly or daily limit. The search/filter
  API has lower limits (5–20 requests/min) and a cap of
  15,000 total results.
- The API accepts ISIN/CUSIP/SEDOL as **input** for mapping, but does **not
  return** them in the response: the documentation states this is due to
  third-party licensing restrictions on those proprietary
  identifiers, not a technical limitation of OpenFIGI.
- Fits directly with `market_relay.ports.discovery.DiscoveryPort`:
  the port is already designed to be neutral, without coupling the core to
  OpenFIGI (design.md § "Hexagonal architecture with governed
  adapters").

## Permissions: retrieve / store / display / redistribute / attribute / retain

Primary evidence consulted: <https://www.openfigi.com/docs/terms-of-service>
and <https://www.openfigi.com/about/faq>.

All the following rows refer **exclusively to the FIGI Identifier**;
none applies to the Related Security Descriptions (see next section).

| Capability | Status | Evidence |
|---|---|---|
| `RETRIEVE` | `GO` | Public, free API, no access cost. |
| `STORE` | `GO` | §1 of the ToS is a **public domain dedication** ("Bloomberg ... hereby dedicates FIGI Identifiers to the public domain"), not an MIT license. It does not impose a retention limit for the FIGI Identifier. |
| `DISPLAY` | `GO` | §1: "you are free ... to use, display, reproduce, distribute and create derivative works from **the FIGI Identifiers**". |
| `REDISTRIBUTE` | `GO` | §1, same sentence: "... including redistribution of **the FIGI Identifiers** to your customers for their use" — directly covers MarketRelay's model of republishing to Holdria, but only the FIGI. |
| `ATTRIBUTE` | `GO` (not required) | The terms do not require mandatory attribution to republish the FIGI; citing "OpenFIGI" is nonetheless recommended as good practice and for provenance transparency. |
| `RETAIN` | `GO` | There is no maximum retention period set in the terms for the FIGI Identifier. |

## Explicit scope limit

This `GO` covers **strictly and exclusively** the FIGI identifier itself
(`figi`), covered by the public domain dedication in §1 of the ToS,
including its explicit redistribution-to-customers clause quoted above.

**It does not cover** the additional non-proprietary fields that the same
mapping API returns alongside the FIGI — security name, ticker, market
code (`exchCode`), market sector (`marketSector`), and security
type (`securityType`), which OpenFIGI's own ToS calls
"Related Security Descriptions". <https://www.openfigi.com/docs/terms-of-service>
was reviewed directly, and those fields **do not appear in any license
grant equivalent to the one in §1**: the only explicit mention of
Related Security Descriptions is in the disclaimer clause (§3, "FIGI IDENTIFIERS AND RELATED SECURITY
DESCRIPTIONS ARE PROVIDED 'AS IS', WITH NO REPRESENTATIONS OR
WARRANTIES..."), which limits Bloomberg's liability, not one that
grants storage or redistribution rights. Their status remains
**`UNRESOLVED`**: **no adapter SHALL store or redistribute
ticker, name, `exchCode`, `marketSector`, or `securityType`** until
that gap is expressly resolved (e.g., a written inquiry to
Bloomberg/OpenFIGI, or legal review).

**Allowlist of fields authorized by this `GO`**: only `figi`. A
future OpenFIGI `DiscoveryPort` SHALL be implemented as a
FIGI-only projection/adapter that discards or never persists the other
fields of the API response, unless a later review explicitly expands
this scope.

It also does not cover, for the reason already noted, third-party ISIN, CUSIP,
or SEDOL: OpenFIGI does not redistribute them (the API itself does not
return them), so there is no scenario in which an OpenFIGI adapter
could accidentally leak those proprietary identifiers
through this channel.

## Ambiguities to resolve operationally

- **Multiple listings per search**: `design.md` already identifies this
  risk ("OpenFIGI may return multiple listings") and the mitigation
  (explicit resolution with MIC, currency, and confirmation on ambiguity) is
  covered by `specs/instrument-catalog/spec.md` § "Ambiguous EUR
  match", not by this document.
- **Bloomberg's limited liability**: the terms cap Bloomberg's
  total liability for FIGI data at USD 50 and provide it "as is", without
  warranties. This is an operational risk to accept, not
  a permissions blocker.

## Why this does not enable an adapter yet

This wave (tasks.md section 3) is for evaluation, not implementation.
Implementing a real `DiscoveryPort` for OpenFIGI and recording the
corresponding `SourcePolicyDecision APPROVED` in the policy registry
is an explicit, pending implementation task, out of scope for
this documentary change. Until then:

- `Settings.enabled_sources` remains `("fake",)`.
- No `SourcePolicyDecision` exists for `source="openfigi"` in the
  schema — `PolicyGate.effective_status` treats it as `UNRESOLVED` due to
  the absence of a recorded decision, never as `APPROVED` by default (the same
  principle verified in `tests/unit/test_policy_gate.py::test_unresolved_capability_blocks_retrieval_by_default`).
- `tests/unit/test_source_viability_gate.py` automatically verifies that
  this remains the case.
