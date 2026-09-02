## Purpose

Keep MarketRelay operable through a portable scheduled execution, bounded work, and sufficient signals to detect delays and failures.

## ADDED Requirements

### Requirement: Portable scheduled entry point
The system SHALL offer a single deployable entry point that refreshes calendars in a bounded way, dispatches eligible work, and processes a limited amount per run.

#### Scenario: Successful periodic run
- **WHEN** the scheduler invokes the entry point
- **THEN** it completes bounded phases and can be run again without duplicate effects

### Requirement: Minimal observability
The system SHALL expose queue depth, age of the oldest pending job, successful scheduler and worker runs, failures by source, and quota status without including secrets.

#### Scenario: Stalled jobs
- **WHEN** the age of the pending job exceeds the configured threshold
- **THEN** the metric allows detecting the delay and identifying the source without revealing credentials

### Requirement: Safe degraded operation
Unavailability of a source SHALL degrade only the dependent instruments and SHALL keep the catalog and previously publishable data available.

#### Scenario: A source stops responding
- **WHEN** an external adapter exhausts its retries
- **THEN** other sources continue and the API retains access to authorized historical observations

