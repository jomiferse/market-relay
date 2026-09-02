# Source Qualification Matrix Template

One row represents one source surface and one capability. Do not aggregate a public website, downloadable dataset, commercial API, and licensed feed into a single row.

| Field | Required content |
|---|---|
| Source ID / surface | Stable ID and exact API, dataset, feed, or page surface |
| Capability | `IDENTIFIER`, `DESCRIPTIVE_METADATA`, `HISTORICAL_EOD`, `LATEST_PRICE`, or `MARKET_CALENDAR` |
| Field allowlist | Exact usable fields; empty when unresolved |
| Technical status | `GO`, `NO-GO`, or `UNRESOLVED`, with protocol/version and response semantics |
| Storage rights | Status, scope, evidence ID, and restrictions |
| Internal presentation rights | Status, intended audience/use, evidence ID, and restrictions |
| Redistribution rights | Status, intended `/v1` downstream use, evidence ID, and restrictions |
| Automated-access permission | Status, method, evidence ID, and restrictions |
| Attribution / retention | Required notices, retention duration, deletion duties, and evidence IDs |
| Terms and robots | Terms version/date; for scraping, exact robots URL, user agent, paths, access time, and result |
| Authentication | None, account, API key, OAuth, or contract; store only the credential-reference type, never a value |
| Rate / concurrency limits | Published quotas, reset semantics, burst/concurrency rules, and evidence ID |
| Coverage | Geography, exchanges/MICs, asset classes, identifier types, history depth, delays, and currencies |
| Documentary status | Derived `GO`, `NO-GO`, or `UNRESOLVED` for the exact capability/use |
| Operational approval | `APPROVED`, `DENIED`, or `PENDING`, accountable owner, ticket/reference, and date |
| Activation status | `DISABLED` for this change |
| Evidence and review | Primary URLs/document IDs, pinpoint locations, access date, reviewer, decision version, review-by date/trigger |
| Open issues / next action | Every evidence, contractual, coverage, or operational gap |

## Evidence Record Template

| Evidence ID | Source surface | Authority | Document title/version | URL or approved reference | Pinpoint scope | Accessed at | Content hash/snapshot reference | Notes |
|---|---|---|---|---|---|---|---|---|
| `E-...` |  | Primary / secondary |  |  | Section/paragraph/endpoint | ISO 8601 | Optional and only where permitted |  |

## Derived Decision Rule

The aggregate row result is `GO` only when technical status is `GO`, every right required for the exact use is explicitly supported, evidence is current, operational approval is `APPROVED`, the field allowlist covers only used fields, and all runtime prerequisites are closed. Any denial yields `NO-GO`; every absence, ambiguity, conflict, expiry, or pending approval yields `UNRESOLVED`. Regardless of that derived result, activation remains `DISABLED` in this change.
