## Why

MarketRelay has a safe provider-neutral foundation, but no real source may be activated until its technical coverage and the rights needed for automated retrieval, storage, internal presentation, and redistribution are supported by current documentary evidence and separate operational approval. The existing review also does not classify sources independently by identifier, descriptive-metadata, historical-EOD, and latest-price capability, which is necessary to compose a lawful workflow from multiple providers.

## What Changes

- Introduce a reproducible, field- and capability-specific source qualification record that separates technical viability, documentary permission, operational approval, and runtime activation.
- Evaluate OpenFIGI, Stooq, Alpha Vantage, Twelve Data, Börse Frankfurt / Deutsche Börse public sources, Euronext public sources, Yahoo Finance, and TradingView using dated primary evidence; absence or ambiguity remains `UNRESOLVED`.
- Record storage, internal presentation, redistribution, automated-access, authentication, rate-limit, coverage, attribution, retention, and—where applicable—terms and `robots.txt` constraints independently.
- Define a validation basket of at least six European instruments across multiple exchanges, including equities and ETFs, beginning with ISIN and targeting canonical resolution plus historical EOD observations.
- Add non-secret, deterministic contract fixtures for qualified response shapes and identifier mappings without calling or enabling a production provider.
- Document capability composition and future source precedence/fallback so identifier, metadata, historical-EOD, latest-price, and calendar roles need not come from one provider.
- Preserve the fail-closed rule: qualification does not seed runtime `APPROVED` decisions, register scraping, add credentials, or enable a real source. Activation requires a later explicit OpenSpec change and documentary plus operational approval.

## Capabilities

### New Capabilities

- `source-qualification`: Evidence-backed classification of provider capabilities, usage rights, access constraints, operational approval, validation fixtures, and activation readiness.

### Modified Capabilities

<!-- No established capability contract is changed by this research and qualification change. -->

## Impact

- Adds OpenSpec requirements, qualification documents, structured non-secret fixtures, and validation tests.
- May produce architecture decision records or follow-up change proposals for capability-separated ports, policy-version provenance, queue recovery, and timeouts, but does not implement those runtime changes in this change.
- Does not change the public `/v1` API, production configuration, enabled source set, database schema, provider registry, or credential handling.
- Establishes evidence and approval prerequisites for any later real-provider implementation or activation change.
