## Purpose

Provide a stable, queryable identity for financial instruments and distinguish each specific listing by market and currency.

## ADDED Requirements

### Requirement: Canonical identity and listings
The system SHALL represent the economic instrument and its listings separately, retaining asset type, known identifiers, ticker, MIC, and currency, without assuming that an ISIN identifies a single listing.

#### Scenario: ISIN with multiple listings
- **WHEN** a search returns the same ISIN traded on multiple markets
- **THEN** the system returns one instrument and listings differentiated by market identifier and currency

### Requirement: Explicit and traceable resolution
The system SHALL resolve external identifiers deterministically, retain the provenance of each match, and reject results that are ambiguous or incompatible with the requested criteria.

#### Scenario: Ambiguous EUR match
- **WHEN** there are several EUR listings and there are not enough criteria to choose one
- **THEN** the system reports the ambiguity without silently linking a listing

### Requirement: MVP asset classes
The catalog SHALL support stocks, ETFs, investment funds, and crypto assets, allowing fields not applicable to a given class to remain absent.

#### Scenario: Crypto asset without ISIN or MIC
- **WHEN** a crypto asset identified by symbol and trading market is registered
- **THEN** the catalog represents it without fabricating an ISIN or MIC

