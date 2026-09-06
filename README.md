# Market Relay

Market Relay is a governed market-data ingestion service for resolving instruments and
storing end-of-day price observations. It provides an authenticated HTTP API, a durable
scheduler, append-only observations, and explicit policy gates for acquiring, storing,
presenting, and redistributing data.

The project is designed for PostgreSQL in production and supports SQLite for local
development and reproducible tests.

## Status

- The foundational `build-market-data-hub` OpenSpec change is complete and archived.
- No external market-data source is enabled.
- Source registration does not imply policy approval or runtime activation.
- The active `qualify-real-market-data-sources` change tracks documentary and operational
  qualification work.
- Scraping is not implemented.

## Core capabilities

- Canonical instrument and listing catalog
- Capability-specific provider interfaces for identifiers, metadata, historical EOD prices,
  latest prices, calendars, and quotas
- Persistent ingestion queue with leases, fencing tokens, retries, deduplication, and bounded
  provider execution
- Append-only observations enforced by application logic and database triggers
- Immutable acquisition and storage-policy provenance
- Dynamic presentation and redistribution policy checks
- Authenticated, scope-restricted `/v1` API
- Secret-safe credential references, error handling, logs, and metrics

## Stack

- Python 3.12
- FastAPI and Pydantic
- SQLAlchemy 2 and Alembic
- PostgreSQL and SQLite
- pytest, Ruff, and mypy
- `uv` for dependency and command management

## Local setup

Install Python 3.12, [`uv`](https://docs.astral.sh/uv/), and the project dependencies:

```bash
uv sync
```

Apply the database migrations. SQLite is used by default and creates
`market_relay.db` in the project directory:

```bash
uv run alembic upgrade head
```

Set local consumer credentials. These values are examples for local development only:

```bash
export MARKET_RELAY_CONSUMER_HOLDRIA_API_KEY="local-holdria-key"
export MARKET_RELAY_CONSUMER_OPS_API_KEY="local-ops-key"
```

Start the API:

```bash
uv run market-relay-api
```

The API is available at `http://localhost:8000`; interactive documentation is available at
`http://localhost:8000/docs`. Send credentials using the `X-API-Key` header.

Run one bounded scheduler cycle:

```bash
uv run market-relay-scheduler
```

The scheduler is intentionally a one-cycle command. Run it from cron, a container scheduler,
or another process supervisor at the desired interval.

## PostgreSQL

Set a SQLAlchemy connection URL before running migrations or services:

```bash
export MARKET_RELAY_DATABASE_URL="postgresql+psycopg://USER:PASSWORD@HOST:5432/DATABASE"
uv run alembic upgrade head
```

Keep real credentials outside source control. Runtime configuration retains opaque credential
references rather than secret values.

## Verification

Run the complete test and static-analysis suite:

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
openspec validate qualify-real-market-data-sources --strict
```

The PostgreSQL migration test uses an ephemeral Docker container and proves that raw updates
and deletes cannot mutate stored observations:

```bash
uv run pytest tests/migrations/test_postgresql_append_only.py
```

## Architecture

```text
Provider capabilities
        |
        v
Scheduler -> persistent queue -> ingestion and validation
                                      |
                                      v
                              append-only observations
                                      |
                         dynamic governance policy gates
                                      |
                                      v
                              authenticated /v1 API
```

Provider capabilities are registered independently. Identifier resolution, descriptive
metadata, pricing, calendar classification, and quota information can come from different
sources. Calendar routing is based on listing venue rather than price-source ordering.

Job claims carry expiring leases and monotonically increasing generations. Completion and
failure updates require the current owner and generation, preventing a stale worker from
overwriting work recovered by another scheduler.

## Source governance

Technical accessibility is never treated as permission. A real source must remain disabled
until evidence explicitly supports the intended automated access, storage, presentation, and
redistribution model, and operational approval has been recorded. Scraping additionally
requires compatible terms, robots.txt evidence, and explicit operational approval.

See:

- [`docs/source-viability/README.md`](docs/source-viability/README.md)
- [`docs/verification.md`](docs/verification.md)
- [`docs/final-openspec-review.md`](docs/final-openspec-review.md)
- [`openspec/changes/qualify-real-market-data-sources/`](openspec/changes/qualify-real-market-data-sources/)

## Repository layout

```text
src/market_relay/   Application, domain, adapters, ports, and migrations
tests/              Unit, integration, concurrency, security, and contract tests
openspec/           Source-of-truth specifications and change artifacts
docs/               Verification and source-viability records
```
