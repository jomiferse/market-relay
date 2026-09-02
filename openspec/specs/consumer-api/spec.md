# Consumer API Specification

## Purpose

Provide Holdria with a stable, secure contract for querying instruments, EOD prices, and statuses without exposing providers or internal secrets.

## Requirements

### Requirement: Versioned and authenticated API
Every non-public operation SHALL require an authorized consumer identity and the API SHALL maintain a versioned contract with structured errors.

#### Scenario: Unauthenticated consumer
- **WHEN** a request lacks valid service credentials
- **THEN** the API rejects it without revealing data, configuration, or the existence of secrets

### Requirement: Catalog and observation queries
The API SHALL allow searching instruments, selecting a listing, and retrieving an EOD observation or range with effective date, currency, provenance, and publication status.

#### Scenario: Range with non-trading days
- **WHEN** Holdria requests a range that contains days without a session
- **THEN** the API returns only effective observations and allows distinguishing an expected absence from pending or failed data

### Requirement: Publication limited by policy
The API MUST exclude observations whose policy does not authorize that consumer and use, even if they are stored.

#### Scenario: Stored data not redistributable
- **WHEN** Holdria requests a stored observation whose redistribution is denied
- **THEN** the API does not return the value and communicates a non-sensitive unavailability status

### Requirement: Isolation of responsibilities
The API MUST NOT receive portfolios, positions, or personal credentials from Holdria's users and MUST NOT claim to offer real-time prices.

#### Scenario: EOD price request
- **WHEN** Holdria queries the latest available data
- **THEN** the response identifies its effective date and EOD nature, not a current real-time price
