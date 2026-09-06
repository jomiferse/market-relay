# Repository Instructions

These instructions apply to every automated coding agent working in this repository.

## Source of truth

- OpenSpec is the source of truth for product behavior and implementation scope.
- Read the relevant proposal, design, specifications, and tasks before changing code.
- Keep OpenSpec tasks accurate: check an item only after implementation and verification.
- Do not archive an OpenSpec change unless the user explicitly requests it.
- Do not expand an active change with speculative cleanup or unrelated refactoring.

## Project constraints

- Use Python 3.12, FastAPI, Pydantic, SQLAlchemy 2, and Alembic.
- PostgreSQL is the production database. SQLite must remain supported for local development
  and reproducible tests.
- Preserve append-only market observations and their database-level protections.
- Keep `/v1` authenticated and enforce operation-specific scopes.
- Keep acquisition/storage authorization provenance immutable. Evaluate presentation and
  redistribution against current policy.
- Provider capabilities must remain independently composable. A single provider must not be
  required to supply identifiers, metadata, prices, calendars, and quota information.
- Preserve durable queue leases, fencing, retries, deduplication, and bounded execution.

## Source governance and security

- Technical accessibility is not permission to use a source.
- Registration must never imply provider activation or policy approval.
- Do not enable an external source without evidence for the intended automated access,
  storage, presentation, and redistribution model plus explicit operational approval.
- Do not implement scraping without compatible terms, robots.txt evidence, and explicit
  operational approval.
- Never commit real provider credentials or consumer secrets.
- Represent credentials through opaque references. Never expose secret values in source,
  logs, metrics, tests, fixtures, persisted errors, documentation, or API responses.
- Do not log arbitrary exception payloads. Persist and expose bounded safe error codes only.

## Code and documentation

- Write code, comments, identifiers, tests, commit messages, and Markdown in English.
- Prefer small, targeted changes that match existing architecture and naming.
- Add regression tests for corrected behavior and tests for every new requirement scenario.
- Preserve public API semantics unless an approved specification requires a change.
- Update migrations for schema changes and verify both SQLite and PostgreSQL behavior.

## Verification

Run the checks relevant to the change. Before declaring a substantial change complete, run:

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
```

Also run strict validation for every affected active OpenSpec change:

```bash
openspec validate <change-name> --strict
```

When database integrity or migrations change, run the migration suite, including the
ephemeral PostgreSQL append-only integration test. Report skipped checks and blockers
explicitly; never present a skipped check as passing.

## Git hygiene

- Preserve unrelated user changes in the working tree.
- Do not rewrite history, force-push, archive changes, or delete data without explicit user
  authorization.
- Do not commit or push unless requested.
