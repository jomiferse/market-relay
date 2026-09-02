## Context

The completed foundation has capability-specific ports and registrations, canonical-listing calendar routing, dynamic publication policy gates, append-only observations and acquisition-policy decisions, fenced job leases, hard provider deadlines, and a disabled-by-default configuration. Automated access and operational approval are not yet first-class qualification dimensions, and no current real source is approved for the complete intended workflow. This change is therefore a qualification and evidence wave, not an activation wave.

## Goals / Non-Goals

**Goals:**

- Produce machine-checkable, human-reviewable decisions at source, capability, field, right, and use-case granularity.
- Establish an offline validation basket and provider contract fixture format without copying unlicensed datasets.
- Demonstrate that future workflows may compose distinct identity, metadata, calendar, historical-EOD, and latest-price sources.
- Identify hard runtime prerequisites that a later implementation or activation change must close.

**Non-Goals:**

- Implementing or enabling a real provider or scraper.
- Creating accounts, accepting terms, buying licenses, or obtaining API keys.
- Treating legal review as automated or substituting this work for counsel or data-owner approval.
- Changing `/v1`, ingesting live observations, or archiving `build-market-data-hub`.

## Decisions

### 1. Use a four-layer decision model

Each source/capability record separates:

1. `technical_status`: `GO`, `NO-GO`, or `UNRESOLVED` for protocol, fields, coverage, history, quotas, and reliability;
2. `documentary_status`: `GO`, `NO-GO`, or `UNRESOLVED` for each right and access dimension;
3. `operational_approval`: `APPROVED`, `DENIED`, or `PENDING` by an accountable operator;
4. `activation_status`: always `DISABLED` in this change.

The effective qualification is fail-closed: a capability is activation-eligible only if every required technical and documentary dimension is `GO`, operational approval is `APPROVED`, evidence is current, and an explicit later activation change accepts it. A single aggregate status is retained only as a derived summary.

Alternative considered: one status per provider. Rejected because it hides field-level restrictions and incorrectly implies that identity, metadata, and price rights travel together.

### 2. Store qualification records as versioned structured fixtures plus narrative evidence

The structured record will include stable source and evidence IDs, capability and field scopes, rights, access method, authentication reference type (never a value), rate-limit facts, coverage, reviewer, timestamps, review trigger, conclusions, and unresolved questions. Narrative files explain interpretation and preserve pinpoint citations. Schema validation and consistency tests prevent a prose conclusion from diverging from its machine-readable status.

Evidence references use official URLs or approved internal document/ticket references. Public excerpts remain short; snapshots or hashes may be recorded where permitted, but copyrighted terms are not copied wholesale into the repository.

Alternative considered: database-backed qualification now. Rejected because this wave is reproducible research with no runtime activation and should not create a migration whose schema is premature.

### 3. Model capabilities and rights as a matrix

Rows identify a provider capability: `IDENTIFIER`, `DESCRIPTIVE_METADATA`, `HISTORICAL_EOD`, `LATEST_PRICE`, or `MARKET_CALENDAR`. Columns identify technical support and the exact usage dimensions: automated retrieval, storage, internal presentation, redistribution through `/v1`, attribution, retention, authentication, quotas, geography, exchanges, and asset classes. Field allowlists further constrain a cell.

This permits OpenFIGI, for example, to retain a documentary conclusion for `figi` without extending it to descriptive response fields. It also permits an identifier source and a price source to be selected independently.

### 4. Treat scraping as an additional three-part gate

For any page-derived source, the matrix adds exact terms evidence, `robots.txt` evidence for the intended paths and user agent, and an operational approval record covering request rate, identification, caching, monitoring, and shutdown. Robots directives are not interpreted as a license. Failure of any part is fail-closed.

### 5. Use synthetic contract fixtures and factual basket metadata

Provider response fixtures contain hand-authored synthetic values shaped like documented contracts; they do not contain copied market-price series. The basket itself contains factual public identifiers and expected mapping constraints. At least six entries cover Xetra and multiple Euronext markets and include equities and UCITS ETFs. Tests validate ambiguity handling, normalization boundaries, provenance fields, and absence of secrets without contacting candidates.

### 6. Keep qualification separate from activation

No qualification output modifies enabled-source settings or seeds runtime approvals. A later provider implementation can exist while disabled, but activation must be a separate reviewed change. That change must bind the exact provider capability and field allowlist to the policy decision versions used by persisted data.

### 7. Verify runtime prerequisites without refactoring in this wave

The foundation now supplies four prerequisites for reliable real-source activation:

- capability-specific registrations and calendar bindings;
- immutable retrieval/storage policy-decision references on observations;
- fenced lease recovery and due promotion of `WAITING_FOR_PUBLICATION` jobs;
- hard provider request deadlines with documented process-isolation constraints.

The qualification report will verify these invariants for any candidate integration and identify only source-specific gaps. This change does not refactor the production runtime during evidence research.

### 8. Preserve a provider-neutral public API and deterministic internal routing

Future routing configuration is keyed by capability and, where needed, venue or asset class. It contains ordered source IDs and requires policy eligibility before selection. Every fallback records its actual source; no response silently merges providers. Current `/v1` resource shapes need not change, although adding an opaque provenance or decision reference may be proposed as an additive extension after the provenance model is settled.

## Risks / Trade-offs

- [Published terms are mutable or incomplete] → Version decisions, record review triggers, prefer primary sources, and fail closed on expiry or ambiguity.
- [A fixture accidentally contains licensed market data or a credential] → Use synthetic values, scan all artifacts for secret patterns, and require reviewer confirmation of fixture origin.
- [An aggregate `GO` hides a restricted field] → Derive summaries from capability/right/field cells and reject records without explicit scopes.
- [Technical tests are mistaken for permission] → Keep technical and documentary statuses separate and require operational approval plus a later activation change.
- [Provider plans become coupled to one vendor] → Maintain capability-specific bindings and validate a composed workflow in design artifacts.
- [Research becomes stale before implementation] → Give every evidence item an access date and review trigger; activation revalidates it.

## Migration Plan

1. Add the qualification schema, matrix template, and validation tests without altering runtime configuration.
2. Populate and review one versioned record for every candidate, using primary evidence and explicit unresolved fields.
3. Add the European basket and synthetic provider-contract fixtures.
4. Publish the capability routing proposal and prerequisite gap report.
5. Verify that all real sources remain disabled and no runtime approval is seeded.
6. Validate this OpenSpec change strictly. A subsequent change may implement prerequisites; another explicit change may activate only a fully qualified source.

Rollback consists of removing the new research artifacts and tests; there is no data migration or production activation to reverse.

## Open Questions

- Which accountable role can grant operational approval and what ticketing/sign-off system will hold that approval?
- Will intended `/v1` consumption legally count as internal presentation, redistribution, or both for each deployment/customer relationship?
- What evidence retention period and re-review interval will counsel or the data owner require?
- Which provider-specific commercial agreements, if any, can be reviewed outside public documentation?
