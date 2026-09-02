"""Absence of credentials in the source-viability documentary artifacts
(tasks.md 3.1: 'verify that the document contains no credentials'). Scans
docs/source-viability/ and its reproducible fixture in
tests/fixtures/source_viability/ for common embedded-secret patterns, just
like market_relay.domain.governance.credentials.sanitize_message does for
runtime messages.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCS_DIR = REPO_ROOT / "docs" / "source-viability"
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "source_viability"

# Common credential patterns embedded in URLs, query strings, or provider
# tokens; deliberately broad for a defensive scan of documentation, not
# just code (unlike credentials._QUERY_SECRET_PATTERN, which sanitizes
# messages on the fly).
_CREDENTIAL_PATTERNS = (
    re.compile(r"://[^/@\s]+:[^/@\s]+@"),  # user:pass@host embedded in a URL
    re.compile(r"(?:api[_-]?key|token|secret|password|apikey)\s*[:=]\s*[^\s,)}\]]{6,}", re.I),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),  # AWS access key id
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bsk_live_[A-Za-z0-9]+\b"),
    re.compile(r"\bghp_[A-Za-z0-9]{20,}\b"),  # GitHub token
)


def _documentary_files() -> list[Path]:
    files = list(DOCS_DIR.rglob("*.md")) + list(FIXTURES_DIR.rglob("*.json"))
    assert files, "no source-viability artifacts found to scan"
    return files


def test_viability_artifacts_exist() -> None:
    assert DOCS_DIR.is_dir()
    assert FIXTURES_DIR.is_dir()
    assert _documentary_files()


def test_no_credential_like_patterns_in_viability_docs_and_fixtures() -> None:
    offending: list[str] = []
    for path in _documentary_files():
        content = path.read_text(encoding="utf-8")
        for pattern in _CREDENTIAL_PATTERNS:
            match = pattern.search(content)
            if match:
                offending.append(f"{path.relative_to(REPO_ROOT)}: {match.group(0)!r}")

    assert not offending, "possible credentials detected:\n" + "\n".join(offending)


def test_viability_fixtures_only_reference_public_http_evidence() -> None:
    """Every `evidence` field in source_decisions.json SHALL be a public
    http(s) URL, never a local path, an opaque credential identifier, or
    a connection value with embedded authentication.
    """

    import json

    data = json.loads((FIXTURES_DIR / "source_decisions.json").read_text(encoding="utf-8"))
    for source in data["sources"]:
        for capability, decision in source["capabilities"].items():
            evidence = decision["evidence"]
            assert evidence.startswith(("http://", "https://")), (
                f"{source['source_id']}.{capability} evidence is not a public URL: {evidence}"
            )
            assert "@" not in evidence, (
                f"{source['source_id']}.{capability} evidence contains a possible "
                "embedded credential"
            )
