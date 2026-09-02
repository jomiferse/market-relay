# Final OpenSpec compliance review

Date: 2026-09-03  
Change: `build-market-data-hub`

Codex reviewed every requirement and scenario after implementation, security
fixes, repository-wide English normalization, and the complete verification
run recorded in [`verification.md`](./verification.md).

## Instrument catalog

- Canonical instruments and separate listings support one ISIN across several
  venues; tests verify differentiated Xetra/Euronext listings.
- Resolution is explicit and traceable. Ambiguous EUR matches fail without a
  silent link, while MIC disambiguation resolves a single listing.
- Stocks, ETFs, funds, and crypto are represented; crypto is verified without
  ISIN or MIC.

## Source governance

- The versioned policy registry defaults missing permissions to `UNRESOLVED`.
  Retrieval requires `RETRIEVE`; ingestion requires `RETRIEVE` plus `STORE`;
  publication requires `STORE`, `DISPLAY`, and `REDISTRIBUTE`.
- Attribution is surfaced when required, and a later policy decision revokes
  access dynamically while preserving the audit trail.
- Credentials are opaque references resolved at use time. Decoy-secret tests
  cover logs, persisted job errors, metrics, HTTP errors, provider failures,
  and consumer authentication.
- The deterministic fake implements discovery, historical data, calendars,
  and quota behavior without network access or real credentials.

## Market-data ingestion

- Recovery planning starts after the last completed session, respects
  lookback and chunk bounds, and recovers several missing sessions.
- Exchange closures produce `NO_SESSION`, delayed fund NAV produces
  `WAITING_FOR_PUBLICATION`, and crypto uses daily 24/7 sessions.
- Queue deduplication, database uniqueness, append-only triggers, expiring
  leases, owner/generation fencing, and concurrent recovery tests cover worker
  crashes, lost confirmation, stale completion, and duplicate execution.
- Waiting-publication jobs promote atomically when due, and provider calls run
  under a hard process-isolated deadline shorter than the lease.
- Exhausted quota defers work without a provider fetch. Malformed observations
  and failing sources remain isolated and recover through bounded retries.

## Market observations

- Each immutable observation retains listing, source, credential scope,
  external identifier, effective date, currency, type, retrieval time,
  quality status, raw close, optional adjusted close, revision, and exact
  append-only retrieval/storage policy decision references.
- Raw `close` is never replaced by `adjusted_close`.
- Selection follows configured source priority, exposes discrepancies, never
  mixes values, and selects the latest revision deterministically.
- Database triggers reject update and delete on SQLite and PostgreSQL paths;
  policy revocation hides data without mutating historical rows.

## Consumer API

- `/v1` exposes authenticated search, listing detail, latest observation,
  ranges, data status, operational status, and operator metrics with validated
  OpenAPI response schemas and structured errors.
- Ranges distinguish `NO_SESSION`, `WAITING_FOR_PUBLICATION`, and
  `UNAVAILABLE`; observation responses include effective date, currency,
  provenance, attribution, revision, discrepancy, and EOD semantics.
- Denied, unresolved, or revoked sources return no observation value or
  effective-date metadata.
- Holdria contract tests prove that no route or response schema accepts or
  exposes portfolio, position, customer, or end-user credential data and that
  no response claims real-time pricing.

## Operations

- One portable scheduler entry point performs bounded refresh, idempotent
  dispatch, leased atomic claims, fenced recovery, and deadline-bounded
  processing. Repeated and concurrent executions do not duplicate jobs or
  observations.
- Durable scheduler-run rows record scheduler and worker phase success or
  failure independently. Metrics expose bounded aggregates for queue depth,
  oldest pending age, successes, failures by source, quota, and stalled
  sources without provider free text or credentials.
- Degradation tests cover unavailable, quota-exhausted, and malformed sources;
  other sources and previously authorized history remain available, and a
  recovered source resumes after backoff.

## Source viability and activation decision

- The representative matrix covers Xetra and Euronext stocks, multiple UCITS
  ETFs, two verified European funds, and EUR crypto with identifiers,
  currencies, raw-close semantics, ranges, missing sessions, quotas, and
  anomalies.
- OpenFIGI is documentary `GO` only for the FIGI identifier under a strict
  `figi` allowlist. Related security descriptions remain `UNRESOLVED`, and no
  OpenFIGI adapter or policy approval is enabled.
- All evaluated real price sources and scraping candidates remain disabled.
  None has complete explicit permission for the intended storage and
  redistribution model; no scraper has the required combined terms,
  `robots.txt`, and operational approval evidence.
- Runtime configuration and adapter registration enable only `fake`.

## Conclusion

All requirements and scenarios, including the independent-verification
remediation, are implemented and verified. The exact command `openspec
validate build-market-data-hub --strict` succeeds. The change is ready for
verification and has not been archived.
