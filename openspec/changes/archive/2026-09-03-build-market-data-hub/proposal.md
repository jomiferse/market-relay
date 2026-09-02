## Why

Holdria needs historical end-of-session prices for different types of assets without being coupled to a specific provider or turning its users' personal credentials into part of the product. MarketRelay will be an independent service that discovers, normalizes, retains, and publishes only data whose source expressly permits the intended use.

## What Changes

- Create a canonical catalog of instruments and quotes for stocks, ETFs, investment funds, and crypto assets, with ISIN, FIGI, ticker, MIC, and currency where applicable.
- Add replaceable adapters for free APIs, open datasets, and sources obtained through permitted scraping; no source will be enabled simply because it is technically accessible.
- Ingest historical series and EOD updates through bounded, retryable, idempotent jobs, with range-based recovery and market calendars.
- Retain the raw value published by the source, especially `close`, along with effective date, provenance, capture time, and quality metadata.
- Model per-source rules on storage, display, redistribution, attribution, retention, and credential scope, blocking publication when there is insufficient evidence.
- Expose an authenticated, versioned API for Holdria to query instruments, observations, and publication status without knowing credentials or internal provider details.
- Separate exchange calendars, funds with delayed publication, and 24/7 crypto markets.
- Add a deterministic provider for development and testing, with no real data or credentials.
- Keep real-time prices, order execution, financial recommendations, and historical adjustment for corporate actions out of the MVP.

## Capabilities

### New Capabilities

- `instrument-catalog`: Canonical identification, search, and resolution of instruments and their tradable quotes.
- `source-governance`: Registration and enforcement of policies, credentials, provenance, and authorization for each source.
- `market-data-ingestion`: Historical and periodic retrieval, normalization, validation, deduplication, and recovery of missing sessions.
- `market-observations`: Retention and deterministic selection of EOD observations for different asset classes.
- `consumer-api`: Authenticated, versioned API through which Holdria consumes catalog, prices, and permitted operational states.
- `operations`: Portable scheduling, retries, usage limits, and minimal observability for the service.

### Modified Capabilities

<!-- No previous capabilities exist: this is a new project. -->

## Impact

- New deployable service and persistent store independent of Holdria.
- External integrations with OpenFIGI as an identification candidate and price providers still subject to technical and usage evaluation.
- Internal HTTP contract between MarketRelay and Holdria, authenticated via service credentials.
- New operational responsibilities: scheduling, queues, quotas, secrets encryption, auditing, metrics, and backups.
- Holdria will retain its observations and valuation rules; MarketRelay will not own portfolios or end-user data.
