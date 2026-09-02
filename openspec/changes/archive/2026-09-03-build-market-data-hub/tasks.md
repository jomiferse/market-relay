## 1. Service foundations

- [x] 1.1 Record a stack, persistence, and deployment decision appropriate for a small service, and verify that it covers scheduled jobs, migrations, tests, and secure secret storage.
- [x] 1.2 Create the executable skeleton, validated configuration, and format/type/test checks, and verify it starts without external credentials.
- [x] 1.3 Define migrations for instruments, listings, external identities, policies/evidence, immutable observations, and jobs, and verify round-trip on an empty database.

## 2. Catalog and source governance

- [x] 2.1 Implement the separate catalog of instruments and listings with lookups by identifier, market, and currency, and verify one-to-many cases and crypto without ISIN.
- [x] 2.2 Implement the versioned registry of policies and evidence with `APPROVED`, `DENIED`, and `UNRESOLVED` states, and verify that a non-approved state blocks retrieval and publication.
- [x] 2.3 Implement opaque credential resolution, encryption/protection, and sanitization, and verify through tests that decoy secrets do not appear in logs, errors, or responses.
- [x] 2.4 Implement neutral interfaces for discovery, historical data, calendars, and quotas alongside the deterministic fake adapter, and verify the flow without network or real secrets.

## 3. Source viability

- [x] 3.1 Create a reproducible matrix with Xetra and Euronext stocks, several UCITS ETFs, European funds, and EUR crypto assets, including identifiers, currency, raw close, ranges, missing sessions, quotas, and anomalous responses; verify that the document contains no credentials.
- [x] 3.2 Evaluate OpenFIGI technically and legally as an identity source, document ambiguities and attribution, and establish `GO`, `NO-GO`, or `UNRESOLVED` with links to public evidence.
- [x] 3.3 Evaluate candidate free price providers by asset class, separating technical viability from storage/redistribution permissions, and verify that no provider without `APPROVED` is left enabled.
- [x] 3.4 Evaluate each candidate scraping source via published terms, `robots.txt`, stability, and limits; implement one only if it receives `APPROVED`, or document that it remains disabled.

## 4. Observations and ingestion

- [x] 4.1 Implement validation and append-only storage of observations with provenance and uniqueness by authorized scope, and verify idempotency under concurrent inserts.
- [x] 4.2 Implement deterministic selection keeping raw `close` separate from `adjusted_close`, and verify discrepancies between values and sources without silent mixing.
- [x] 4.3 Implement calendars and differentiated expectations for exchange listings, fund NAV, and 24/7 crypto, and verify closed market and `WAITING_FOR_PUBLICATION`.
- [x] 4.4 Implement range-based retrieval planning, bounded splitting, and progress cursors, and verify recovery of several missed sessions.
- [x] 4.5 Implement persistent queue, concurrent claims, retries, backoff, quotas, and failure isolation, and verify re-execution, exhausted quota, and malformed response.

## 5. Consumer API

- [x] 5.1 Define and publish the versioned contract for search, listings, latest observation, ranges, and statuses, and verify it with automatic schema validation.
- [x] 5.2 Implement consumer authentication and authorization with non-sensitive error responses, and verify allowed access, denied access, and invalid credentials.
- [x] 5.3 Implement catalog and observation endpoints applying the publication policy gate, and verify that unauthorized stored data is never returned.
- [x] 5.4 Add contract tests representing Holdria that validate effective date, currency, provenance, attribution, status, and EOD semantics without sending portfolio data.

## 6. Operations and verification

- [x] 6.1 Implement the single scheduled entry point with bounded refresh, dispatch, and processing, and verify that repeated executions do not duplicate work or observations.
- [x] 6.2 Expose sanitized metrics for queue depth, pending age, successes, failures by source, and quota, and verify alerts on stalled jobs without secrets.
- [x] 6.3 Add degradation and recovery tests demonstrating that a down source does not affect other sources or publishable history.
- [x] 6.4 Run unit, integration, contract, migration, concurrency, and security tests; fix regressions and record reproducible commands and results.
- [x] 6.5 Run `openspec validate build-market-data-hub --strict` and a final review of all requirements and scenarios before declaring the change ready for verification.

## 7. Independent verification remediation

- [x] 7.1 Add expiring job leases, deterministic concurrent recovery of stale `CLAIMED` and `RUNNING` jobs, and generation/owner fencing on every state transition; verify crash, expiry, retry, stale-worker, and no-double-completion tests.
- [x] 7.2 Promote due `WAITING_FOR_PUBLICATION` jobs atomically without duplicating redispatch; verify before, exact, overdue, and concurrent eligibility tests.
- [x] 7.3 Enforce a configurable hard provider deadline with safe timeout errors, retries, and lease interaction; verify with a deliberately non-cooperative blocking provider.
- [x] 7.4 Split provider registration by discovery, descriptive metadata, historical EOD, latest price, calendar, and quota capability while retaining fail-closed activation; verify identity and price providers can be composed independently.
- [x] 7.5 Route calendars independently by canonical listing and venue rather than price-source precedence; verify venue routing, precedence independence, and deterministic missing-calendar behavior.
- [x] 7.6 Replace arbitrary global exception logging with a generic error code, correlation identifier, and allowlisted context; verify secret-bearing and harmless exception payloads never reach logs.
- [x] 7.7 Persist immutable retrieval/storage policy decision references with each observation while keeping presentation and redistribution dynamically evaluated; verify complete provenance, policy revocation, and append-only behavior.
- [x] 7.8 Add and execute a maintained ephemeral PostgreSQL migration test proving raw observation `UPDATE` and `DELETE` are rejected and the original row remains present.
