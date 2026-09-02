# Market Observations Specification

## Purpose

Retain immutable, traceable market observations without hiding differences between sources or altering the originally published value.

## Requirements

### Requirement: EOD observation with provenance
Each observation SHALL include listing and canonical instrument identity, effective date, value, currency, source, original provider identifier, authorized scope, retrieval instant, quality status, and immutable references to the exact retrieval and storage decisions that authorized acquisition. Presentation and redistribution SHALL continue to use current policy rather than a permanent snapshot.

#### Scenario: Valid daily close
- **WHEN** an approved source returns the close of a session for the requested listing
- **THEN** the system retains an observation associated with that date and its full provenance

#### Scenario: Policy changes after acquisition
- **WHEN** presentation or redistribution policy changes after an observation was stored
- **THEN** its acquisition decision references remain unchanged while current publication eligibility reflects the latest policy

### Requirement: Raw value with no implicit adjustments
For EOD OHLC, the system SHALL retain the published raw `close` and MUST NOT replace it with `adjusted_close`; adjustments for splits, dividends, or other corporate actions are out of scope for the MVP.

#### Scenario: Close different from adjusted close
- **WHEN** a source returns both values with different amounts
- **THEN** the valuation observation uses `close` and retains the distinction without replacing it

### Requirement: Deterministic selection without silent mixing
The system SHALL return observations according to an explicit source and quality policy, without merging values from different sources as if they were equivalent.

#### Scenario: Two approved sources differ
- **WHEN** there are different closes for the same listing and date
- **THEN** the response identifies the selected value, its source, and the policy applied

### Requirement: Preserved history
Corrections or deactivations SHALL preserve prior observations and decisions for audit purposes, marking them as non-publishable when appropriate.

#### Scenario: Revoked source
- **WHEN** a source's publication authorization is revoked
- **THEN** its history remains auditable but no longer appears in ordinary responses
