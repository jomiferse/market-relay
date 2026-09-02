## Purpose

Defines a reproducible, fail-closed process for qualifying real market-data sources by capability, rights, technical constraints, and operational approval before any source can be activated.

## ADDED Requirements

### Requirement: Capability-specific qualification
Each candidate source SHALL be classified independently for identifier data, descriptive instrument metadata, historical EOD prices, and latest prices. A result for one capability SHALL NOT imply a result for another capability or require one source to provide every capability.

#### Scenario: Identifier-only source
- **WHEN** evidence permits use of an identifier field but does not establish rights for descriptive metadata or prices
- **THEN** the identifier capability is recorded at its supported status and every unsupported or unevidenced capability remains `UNRESOLVED` or `NO-GO`

#### Scenario: Composed workflow
- **WHEN** the proposed validation workflow uses different qualified sources for identifier resolution, metadata, historical EOD prices, latest prices, or calendars
- **THEN** the qualification output records each role and its provenance independently without treating any provider as the universal authority

### Requirement: Rights and access dimensions
For every source and applicable capability, the qualification record SHALL separately state storage rights, internal display or presentation rights, redistribution rights, automated-access permission, attribution and retention obligations, authentication or API-key requirements, published rate limits, geographic and exchange coverage, asset-class coverage, and operational approval status.

#### Scenario: Ambiguous permission
- **WHEN** official evidence does not expressly establish a required right for the intended use
- **THEN** that dimension is `UNRESOLVED` and neither technical accessibility nor a free price tier is treated as permission

#### Scenario: Restricted redistribution
- **WHEN** storage and internal presentation are supported but redistribution is denied or unresolved
- **THEN** qualification records the distinctions and the source is ineligible for the MarketRelay consumer API use case

### Requirement: Evidence-backed and reviewable decisions
Every non-`UNRESOLVED` status SHALL cite dated, primary documentary evidence and record the reviewer, review date, decision version, precise scope or field allowlist, and next review trigger. Conflicting, unavailable, expired, or secondary-only evidence SHALL be recorded and SHALL result in `UNRESOLVED` unless authoritative evidence resolves it.

#### Scenario: Terms change
- **WHEN** a cited document changes, disappears, expires, or reaches its scheduled review date
- **THEN** the prior decision remains auditable, a new version is created, and activation eligibility fails closed until the current version is reviewed

#### Scenario: Field-level grant
- **WHEN** a grant applies only to named response fields
- **THEN** the qualification includes an explicit allowlist and all other returned fields remain prohibited from fixtures, persistence, presentation, and redistribution

### Requirement: Scraping qualification gate
For a source accessed by scraping, qualification SHALL require compatible terms of service, a reviewed `robots.txt` applicable to the exact user agent and paths, and explicit operational approval. Missing or ambiguous evidence in any of the three dimensions SHALL prevent scraper implementation and activation.

#### Scenario: Robots permission without terms permission
- **WHEN** `robots.txt` permits a path but terms do not expressly permit the intended automated access and use
- **THEN** the scraping candidate remains disabled and `UNRESOLVED` or `NO-GO`

#### Scenario: Documentary evidence without operational approval
- **WHEN** terms and `robots.txt` are compatible but operational approval is absent
- **THEN** no scraper is implemented or activated

### Requirement: Candidate evaluation coverage
The initial qualification SHALL evaluate OpenFIGI, Stooq, Alpha Vantage, Twelve Data, Börse Frankfurt / Deutsche Börse public sources, Euronext public sources, Yahoo Finance, and TradingView. Each candidate SHALL have a complete record even when every substantive result is `UNRESOLVED` or `NO-GO`.

#### Scenario: Candidate lacks public licensing evidence
- **WHEN** research finds technical documentation but no authoritative grant matching the intended storage and redistribution model
- **THEN** the record identifies the evidence gap and leaves the source disabled

### Requirement: European validation basket
The qualification SHALL define at least six European instruments across multiple exchanges and SHALL include both equities and ETFs. Each basket entry SHALL begin with a verified ISIN and include expected canonical identity, listing identity, MIC, venue, currency, asset class, and the intended EOD observation semantics.

#### Scenario: Same ISIN has multiple listings
- **WHEN** a basket ISIN maps to more than one listing
- **THEN** the expected result distinguishes listings by at least MIC and currency and does not silently select an ambiguous candidate

#### Scenario: Reproducible end-to-end fixture
- **WHEN** the qualification fixtures are validated offline
- **THEN** they demonstrate ISIN input through canonical resolution and a normalized EOD observation shape without live network calls, secrets, or unapproved provider data

### Requirement: Qualification is not activation
Completing documentary or technical qualification SHALL NOT enable a source, seed an `APPROVED` runtime policy decision, install a production credential, execute scraping, or make live provider calls in automated tests. A future activation SHALL require a separate explicit change whose review confirms documentary and operational approval for the exact capabilities and fields used.

#### Scenario: Technically viable provider
- **WHEN** a provider passes contract fixtures and coverage checks but operational approval is absent
- **THEN** its implementation state may be documented but its runtime activation state remains disabled

#### Scenario: Repository default after qualification
- **WHEN** this change is complete
- **THEN** no real source is enabled by default and tests prove that qualification records cannot bypass runtime policy gates

### Requirement: Auditable provenance readiness
The qualification SHALL assess whether future records can preserve provider or source, retrieval timestamp, observation date, original provider identifier, canonical instrument and listing identifiers, and the exact policy or license decision version authorizing retrieval, storage, presentation, and redistribution.

#### Scenario: Missing policy-version link
- **WHEN** the current model cannot identify the exact governing decision versions for a stored observation
- **THEN** the qualification records a prerequisite architecture gap and blocks activation until a scoped follow-up change closes it

### Requirement: Precedence and fallback readiness
The qualification SHALL propose precedence and fallback independently per capability while keeping the public API provider-neutral. Fallback SHALL never combine fields or observations from different sources without explicit provenance and deterministic selection rules.

#### Scenario: Preferred price source unavailable
- **WHEN** a future preferred historical-EOD source is unavailable and an independently approved fallback exists
- **THEN** the design can select the fallback without changing the public resource shape, and the returned provenance identifies the selected source

#### Scenario: No approved fallback
- **WHEN** the preferred source fails and no fallback has all required approvals
- **THEN** the system reports unavailable data and does not use an unapproved source
