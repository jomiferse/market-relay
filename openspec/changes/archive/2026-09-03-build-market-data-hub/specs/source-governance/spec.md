## Purpose

Prevent MarketRelay from capturing or publishing data without an identified source, protected credentials, and evidence of compatible use.

## ADDED Requirements

### Requirement: Policy-governed activation
Each source SHALL separately declare whether it permits retrieval, storage, display, redistribution, attribution, and retention for the intended use. The system MUST prevent ingestion or publication when the required permission is denied or unresolved.

#### Scenario: Technically accessible API without redistribution permission
- **WHEN** a source responds correctly but its redistribution policy is unresolved
- **THEN** the system does not publish its observations to consumers

#### Scenario: Approved source requiring attribution
- **WHEN** an approved source requires attribution
- **THEN** every published response contains the required attribution and provenance

### Requirement: Evidence and review
The system SHALL retain, for each policy decision, the evidence source, review date, and `APPROVED`, `DENIED`, or `UNRESOLVED` status, without inferring approval from technical access.

#### Scenario: Changed terms
- **WHEN** a review changes a policy to `DENIED` or `UNRESOLVED`
- **THEN** new retrievals and affected publications are stopped without deleting the audit history

### Requirement: Credential protection
Credentials SHALL remain exclusively on the server, encrypted or protected according to the environment, never returned in plain text, and never included in logs, metrics, fixtures, errors, or responses.

#### Scenario: Provider authentication error
- **WHEN** a provider rejects a credential
- **THEN** the system logs a sanitized error without including the secret or the full URL if it contains one

### Requirement: Safe test adapters
The system SHALL provide a deterministic source that requires no external access or real credentials.

#### Scenario: Repeatable end-to-end test
- **WHEN** the same scenario is run twice against the deterministic source
- **THEN** it produces the same observations and effective statuses

