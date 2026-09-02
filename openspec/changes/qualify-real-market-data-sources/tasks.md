## 1. Qualification Model and Safety Rails

- [ ] 1.1 Define and JSON-schema validate the versioned source-qualification record, including capability, field allowlist, rights, evidence, access, coverage, review, operational-approval, and activation dimensions; verify valid and intentionally incomplete examples produce the expected pass/fail results
- [ ] 1.2 Add consistency checks that derive aggregate status fail-closed and reject implied approval, missing primary evidence for a non-`UNRESOLVED` status, stale review metadata, or a capability result broader than its field allowlist; verify focused unit tests pass
- [ ] 1.3 Add security checks proving qualification artifacts, synthetic fixtures, logs, and test output contain no credential values or live API keys; verify the repository secret-pattern test passes
- [ ] 1.4 Add an invariant test proving every real candidate remains absent from default enabled sources and no runtime `APPROVED` decision is seeded; verify the test fails against an intentionally enabled test configuration

## 2. Capability and Evidence Research

- [ ] 2.1 Re-evaluate OpenFIGI using current primary terms and API documentation for identifier and descriptive-metadata fields separately; verify the record preserves a `figi`-only allowlist unless explicit evidence broadens it and records every remaining question as `UNRESOLVED`
- [ ] 2.2 Evaluate Alpha Vantage and Twelve Data separately for identifier, metadata, historical-EOD, and latest-price capabilities and every rights/access dimension; verify each conclusion has dated primary evidence or is `UNRESOLVED`
- [ ] 2.3 Evaluate Börse Frankfurt / Deutsche Börse and Euronext public sources, distinguishing web pages, datasets, APIs, and licensed products rather than combining them under one status; verify each source surface has its own evidence and coverage record
- [ ] 2.4 Evaluate Stooq for technical coverage, authoritative terms, automated access, storage, presentation, redistribution, and applicable `robots.txt`; verify technical accessibility alone cannot yield documentary `GO`
- [ ] 2.5 Evaluate Yahoo Finance and TradingView for the exact intended automated-access and downstream-use model; verify consumer-facing page or API accessibility is not treated as storage or redistribution permission
- [ ] 2.6 Peer-review all candidate records for pinpoint scope, contradictions, access dates, review triggers, and unresolved items; verify every initial candidate has a complete schema-valid record

## 3. Scraping and Operational Approval

- [ ] 3.1 For each page-derived candidate, record current terms evidence and the exact applicable `robots.txt` path/user-agent analysis; verify a missing, unreachable, ambiguous, or incompatible input forces a fail-closed result
- [ ] 3.2 Define the operational-approval checklist covering owner, access identity, rate and concurrency limits, caching, monitoring, incident shutdown, change detection, and approval ticket; verify no candidate is marked operationally approved without a completed authoritative record
- [ ] 3.3 Produce a scraper eligibility report without implementing a scraper; verify every candidate lacking all three gates—terms, `robots.txt`, and operational approval—is explicitly disabled

## 4. European Validation Basket and Contract Fixtures

- [ ] 4.1 Finalize at least six factual basket entries across multiple European exchanges, including equities and ETFs, with verified ISIN, canonical identity expectation, MIC, venue, currency, asset class, and raw-EOD semantics; verify schema and duplicate/ambiguity checks pass
- [ ] 4.2 Add synthetic, license-safe fixtures for identifier resolution, descriptive metadata, historical-EOD, and latest-price provider contracts; verify fixtures contain no copied price series, network dependency, or secret and cover malformed, ambiguous, throttled, and unavailable responses
- [ ] 4.3 Specify and test the offline composed flow from ISIN to canonical instrument and listing to normalized EOD observation provenance using distinct hypothetical capability providers; verify the fixture proves no single-provider assumption

## 5. Architecture and Activation Readiness

- [ ] 5.1 Document capability-specific routing and deterministic precedence/fallback rules for identifier, metadata, calendar, historical-EOD, and latest-price roles; verify the proposal preserves the public API and forbids unapproved fallback or silent source mixing
- [ ] 5.2 Verify candidate integration plans use capability-separated adapter registration and canonical-listing calendar routing; confirm each source implements only the ports it supports
- [ ] 5.3 Verify immutable acquisition provenance covers source, retrieval timestamp, observation date, original provider identifier, canonical instrument/listing identifiers, and governing retrieval/storage decision versions
- [ ] 5.4 Verify activation plans preserve abandoned-claim leases, `WAITING_FOR_PUBLICATION` promotion, provider deadlines, and concurrent-worker fencing; confirm scenarios cover retries, crashes, duplicate dispatch, timeout, and late worker completion
- [ ] 5.5 Create an activation-readiness report per candidate listing every failed or unresolved prerequisite; verify none can be marked activation-ready unless all technical, documentary, operational, provenance, and reliability prerequisites are satisfied

## 6. Final Verification

- [ ] 6.1 Run all focused qualification, fixture, security, and disabled-source tests plus the full test suite, Ruff, and mypy; record exact commands and results
- [ ] 6.2 Run `openspec validate qualify-real-market-data-sources --strict` and review every requirement and scenario against delivered evidence; record complete, incomplete, and `UNRESOLVED` items without changing them to favorable statuses for completion
- [ ] 6.3 Confirm the change contains no live calls, production adapters, scraping implementation, credentials, runtime approvals, or enabled real sources; verify by repository search and configuration tests
