## Context

MarketRelay starts as a new service and contains no Holdria portfolios or accounts. It must combine heterogeneous sources with different identities, frequencies, quotas, and permissions. Technical access does not equal authorization to store or redistribute; see `proposal.md` and `specs/source-governance/spec.md`.

## Goals / Non-Goals

**Goals:**

- Keep a core neutral with respect to providers and asset classes.
- Make every identifier, observation, and publication decision traceable.
- Allow historical backfill and incremental EOD updates with bounded cost and quota.
- Give Holdria a small, stable, private contract.

**Non-Goals:**

- Real time, trading, advisory, portfolio valuation, or end-user accounts.
- Inferring licenses from an API or page being publicly accessible.
- Adjusting historical data for corporate actions or synthesizing prices across sources.
- Building a generic distributed scraping platform in the MVP.

## Decisions

### Stack, persistence, and deployment

The service will be implemented with Python 3.12, FastAPI, and Pydantic for the HTTP contract and configuration, SQLAlchemy 2 for persistence, and Alembic for migrations. PostgreSQL will be the deployment engine and the reference for concurrent claims; SQLite will only be supported as a local and reproducible-testing path, keeping the same uniqueness and idempotency constraints in that dialect too. Pytest will cover unit, integration, contract, migration, concurrency, and security tests, and Ruff and mypy will provide formatting, linting, and typing.

Deployment will be a stateless container with two entry points over the same package: API and bounded scheduled execution. The database will retain catalog, policies, observations, and queue; no process will depend on local memory to resume work. Secrets will not reside in tables or artifacts: the configuration will only retain opaque identifiers, and adapters will resolve them from the environment's secrets manager — environment variables only for development — right before use, with centralized sanitization of errors and logs. No external source will be enabled by default; only the deterministic fake provider will be active until technical and permissions evaluation produces `APPROVED` evidence for each required capability.

This stack is chosen for its strict validation, OpenAPI contract, reversible migrations, transactional primitives, and a small deployment path without introducing an external broker. The alternative of a separately managed queue or scheduler increases operations and is not necessary for the MVP's volume.

### Separate instrument, listing, external identity, and observation

An economic instrument will have zero or more listings; each listing represents market, ticker, and currency. Provider identifiers will be linked with provenance and validity. This avoids arbitrarily choosing between Xetra, Euronext, or other markets. The alternative of using ISIN or ticker as the unique key is insufficient due to one-to-many relationships and reused symbols.

### Hexagonal architecture with governed adapters

The core defines independent ports and registrations for discovery, descriptive metadata, historical EOD prices, latest prices, calendars, quotas, and policies. A source implements only the capabilities it actually supplies: an OpenFIGI-like identity adapter can therefore compose with an unrelated price source and venue calendar. Calendar routing uses canonical listing attributes, preferring MIC and then venue, and never price-source priority. Each source remains independently activated through verified policy; registration alone grants nothing. A deterministic fake covers the full flow. Hardcoding providers directly into publication logic is ruled out.

### Policy gate before retrieval and publication

A versioned registry will describe, per source and use, the `retrieve`, `store`, `display`, `redistribute`, `attribute`, and `retain` capabilities, with evidence and review. Two independent controls will act before retrieval and before responding to a consumer. This way, a change in terms halts new exposure without destroying the audit trail. A single boolean list of approved providers does not express partial permissions or retention.

### Isolated central credentials

The MVP will not expose BYOK to Holdria. Operational secrets will live outside the code, be referenced by opaque identifier, and be resolved only inside the adapter. Logs and errors will pass through sanitization. The model will retain a `credentialScope` to support different accounts and avoid unauthorized deduplication, even though initially there is only a single credential per source.

### Immutable storage and idempotency keys

Observations are inserted append-only with uniqueness by `(source, credentialScope, externalListingId, sessionDate, observationType)`. Corrections produce a new revision, not silent overwrite. Every new observation immutably references the exact `RETRIEVE` and `STORE` decision versions that authorized acquisition; those policy-decision rows are append-only as well. Presentation and redistribution are deliberately not snapshotted because they are actions authorized dynamically at query time and may be revoked. Publication selects via explicit current rules. This preserves auditability and allows a future source with a central license to use global scope without changing the domain.

### Single scheduler with a persistent queue

A portable execution performs bounded calendar refresh, pending-range computation, dispatch, and limited consumption. Every claim has a configured lease, owner, and monotonically increasing generation. Concurrent recovery atomically moves expired `CLAIMED` or `RUNNING` jobs back to retry (or terminal failure), clears ownership, and increments the generation. Every running, waiting, retry, failure, and completion transition compares both owner and generation, so a late former worker is fenced and cannot overwrite the current result. Due `WAITING_FOR_PUBLICATION` jobs are atomically promoted to `PENDING`; idempotent redispatch retains one row.

Synchronous provider retrieval executes in a short-lived isolated POSIX child process with a configured hard wall-clock deadline shorter than the claim lease. A timeout terminates the child and becomes the bounded `provider_timeout` failure code, after which normal retry rules apply. This avoids relying on cooperative cancellation. The limitation is explicit: the mechanism requires the Linux/POSIX `fork` context, provider methods must not use inherited database sessions, and adapter response values must be serializable through the process pipe. The scheduled entry point is a dedicated process; calling the provider executor from a multi-threaded host is unsupported because forking a multi-threaded Python process can deadlock.

### Different strategies by frequency

Stocks and ETFs are governed by calendar and listing close; funds use NAV date and a configurable publication window; crypto uses 24/7 daily UTC sessions. `WAITING_FOR_PUBLICATION` does not consume error budget. Raw `close` is stored separately from adjusted values, which do not take part in MVP selection.

### Internal read API

Holdria will authenticate via a service identity with limited permissions. Versioned endpoints will cover search, listing detail, latest observation, and ranges. Responses will contain effective date, EOD nature, currency, permitted provenance/attribution, and status. Credentials, internal quota details, and observations blocked by policy will not be exposed.

## Risks / Trade-offs

- [Free sources may change coverage or limits] → Viability matrix, replaceable adapters, metrics, and manual prices in Holdria.
- [OpenFIGI may return multiple listings] → Explicit resolution with MIC, currency, and confirmation on ambiguity.
- [Scraping may breach terms or break] → Disabled unless favorable evidence, review of `robots.txt` and terms, conservative limits, and contract tests.
- [Funds publish NAV late or irregularly] → Windows by type/source and a non-error waiting state.
- [The central service becomes an operational dependency] → Read API available with historicals, bounded processing, backups, and per-source degradation.
- [Raw close does not reflect splits] → Visible limitation; corporate actions are left for a later capability.

## Migration Plan

1. Create the skeleton, persistence, deterministic fake, and contract tests.
2. Implement catalog, policies, and API with no external sources enabled.
3. Run technical and usage spikes with a representative European matrix per source.
4. Activate only adapters with approved evidence and observe them in a non-production environment.
5. Connect Holdria through its neutral port and gradually migrate eligible links.

Rollback disables the publication policy or the consumer without deleting observations. Holdria retains its manual prices and previously imported data per its own policy.

## Open Questions

- Choose during implementation the stack and persistence engine consistent with the available deployment environment.
- Determine exact operational thresholds after measuring the first source matrix; they do not alter the defined states or contracts.
