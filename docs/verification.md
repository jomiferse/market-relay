# Verification record

Date: 2026-09-03

This record captures the reproducible verification performed for the
`build-market-data-hub` OpenSpec change. All commands were run from the
repository root with Python 3.12 and the locked `uv` environment.

## Static checks

```text
uv run ruff check .                  All checks passed
uv run ruff format --check .         138 files already formatted
uv run mypy src tests                No issues in 109 source files
```

## Test suites

```text
uv run pytest -q                     221 passed, 7 warnings
uv run pytest tests/unit -q          106 passed, 1 warning
uv run pytest tests/integration -q   43 passed, 1 warning
uv run pytest tests/contract -q      10 passed, 3 warnings
uv run pytest tests/migrations -q     8 passed, 1 warning
uv run pytest tests/concurrency -q   11 passed, 5 warnings
uv run pytest tests/security -q      27 passed, 1 warning
uv run pytest tests/quality -q       10 passed, 1 warning
```

The warnings are dependency deprecations from Starlette's current test client
compatibility layer and `jsonschema.RefResolver`, plus a Python warning caused
by the thread-based concurrency test invoking the production POSIX process
isolation path. The scheduler is deployed as a dedicated process; invoking its
fork-based provider executor from a multi-threaded host is explicitly
unsupported and documented in `design.md`.

## Independent verification remediation

- Expiring leases recover stale `CLAIMED` and `RUNNING` work atomically.
  Owner plus generation fences every subsequent transition and prevents late
  workers from overwriting a replacement.
- Due `WAITING_FOR_PUBLICATION` work is atomically promoted to `PENDING`, while
  idempotent redispatch retains one job.
- Synchronous provider retrieval runs in a killable POSIX child with a hard,
  configurable deadline shorter than the job lease. Timeout errors persist
  only the bounded `provider_timeout` code and use normal retry policy.
- Provider capabilities and calendar routes are registered independently;
  calendars resolve by canonical MIC/venue rather than price priority.
- The global API handler logs no exception or request payload, only a generic
  code and generated correlation ID.
- New observations reference the exact append-only `RETRIEVE` and `STORE`
  decisions used at acquisition. Presentation and redistribution remain
  dynamically governed.
- The migration suite launches ephemeral PostgreSQL 17 and proves migrations
  apply, raw observation updates/deletes fail, and the row remains present.

## OpenSpec and language policy

```text
openspec validate build-market-data-hub --strict
Change 'build-market-data-hub' is valid
```

The repository-wide language policy test scans project-owned Markdown,
Python, and JSON, plus project file and directory names. An independent
search found no Spanish prose or identifiers. The only retained Spanish
values are three explicitly marked forbidden-field test values in the
Holdria contract test (`cartera`, `posicion`, and `posición`); they are test
inputs needed to prove that those fields are absent from the API contract.

## Source activation result

Only the deterministic fake provider is enabled. OpenFIGI has a documentary
`GO` solely for the FIGI identifier under a strict `figi` field allowlist,
but no real adapter is enabled. Related security descriptions remain
`UNRESOLVED`. Every evaluated price provider and scraping candidate remains
disabled because storage and redistribution permission is absent, denied, or
unresolved. No scraping implementation was activated.
