# Market Data Ingestion Specification

## Purpose

Retrieve historical and periodic data from multiple sources in a bounded, reliable, quota-respectful way that is recoverable after interruptions.

## Requirements

### Requirement: Range-based retrieval
Synchronization SHALL request from the last completed session up to the last session whose publication is expected, respecting configured age and size limits.

#### Scenario: Several missing sessions
- **WHEN** the service was stopped for several market sessions
- **THEN** the next synchronization recovers the pending range in bounded jobs

### Requirement: Calendar and publication by class
The system SHALL distinguish exchange sessions, deferred fund publications, and 24/7 crypto markets, and SHALL represent data not yet published as waiting, not as failure.

#### Scenario: Closed market
- **WHEN** no session is expected for a listing on a given date
- **THEN** no quota is consumed requesting a price for that date

#### Scenario: NAV not yet published
- **WHEN** the day has ended but the fund's NAV remains within its expected window
- **THEN** the job remains `WAITING_FOR_PUBLICATION` without counting as an error

### Requirement: Idempotency and concurrency
Ingestion SHALL be retry-safe, SHALL recover expired claimed or running work, SHALL fence former claim owners, and SHALL prevent duplicates for the same source, authorized scope, listing, and effective date even with concurrent workers.

#### Scenario: Retry after lost confirmation
- **WHEN** a completed job is run again
- **THEN** it does not duplicate the observation or publish contradictory events

#### Scenario: Worker crashes after claiming work
- **WHEN** a worker does not complete before its claim lease expires
- **THEN** one replacement can recover the work and the former worker cannot later change its state

#### Scenario: Waiting publication becomes due
- **WHEN** a waiting publication reaches its deterministic retry instant
- **THEN** it becomes claimable exactly once without creating a duplicate job

### Requirement: Quotas and partial failures
The system SHALL apply per-source limits, a hard provider deadline, backoff, and bounded retries, isolating failed instruments so they do not prevent processing of others.

#### Scenario: Provider does not return
- **WHEN** a provider exceeds its configured execution deadline
- **THEN** isolated execution is terminated and the job receives a safe bounded timeout failure eligible for normal retry

#### Scenario: Exhausted quota
- **WHEN** a source reports that its quota is exhausted
- **THEN** work is deferred until an allowed window without continuing to make useless requests

#### Scenario: Malformed response
- **WHEN** a response fails schema, identifier, or currency validation
- **THEN** that response is rejected, a sanitized failure is logged, and the other jobs continue
