"""Repository-wide language policy: project Markdown, Python, and JSON
source must read as English prose, never Spanish (repository-wide
language rule), and project-owned directory/file names must be English.

This guards against regressions the same way the rest of the security
suite guards against credential leaks: a scanner that is precise enough to
run unattended in CI, layered so that a single signal (diacritics, a
Spanish-only stopword, or a Spanish JSON object key) is enough to flag
real prose or an untranslated identifier, while URLs, fenced/inline code,
and technical string values (paths, identifiers, enum-like constants) are
stripped or exempted first. See `_language_scan.py` for the detection
rules.
"""

from __future__ import annotations

from pathlib import Path

from tests.quality._language_scan import (
    REPO_ROOT,
    Finding,
    find_spanish_named_paths,
    scan_json_text,
    scan_markdown_text,
    scan_python_text,
    scan_repository,
)

_MEMORY_PATH = Path("<memory>")


def test_scanner_flags_a_representative_spanish_python_docstring() -> None:
    source = '''
def f() -> None:
    """Calcula el precio medio de cierre para el instrumento dado."""
    pass
'''
    findings = scan_python_text(source, path=_MEMORY_PATH)
    assert findings, "the scanner should flag an obviously Spanish docstring"


def test_scanner_flags_a_representative_spanish_comment() -> None:
    source = "x = 1  # este es un comentario en español sobre la fuente\n"
    findings = scan_python_text(source, path=_MEMORY_PATH)
    assert findings


def test_scanner_flags_a_representative_spanish_assertion_message() -> None:
    source = 'assert 1 == 1, "el valor no coincide con lo esperado"\n'
    findings = scan_python_text(source, path=_MEMORY_PATH)
    assert findings


def test_scanner_flags_representative_spanish_markdown_prose() -> None:
    text = "## Resumen\n\nEsta fuente todavía no tiene evidencia suficiente para aprobarse.\n"
    findings = scan_markdown_text(text, path=_MEMORY_PATH)
    assert findings


def test_scanner_does_not_flag_clean_english_python_source() -> None:
    source = '''
def compute_mean_close(prices: list[float]) -> float:
    """Computes the mean closing price for the given instrument."""
    # Guard against an empty series before dividing.
    if not prices:
        raise ValueError("prices must not be empty")
    return sum(prices) / len(prices)
'''
    assert scan_python_text(source, path=_MEMORY_PATH) == []


def test_scanner_does_not_flag_urls_or_technical_identifiers() -> None:
    source = '''
SOURCE_ID = "de-index-provider"
EVIDENCE_URL = "https://example.com/es/terminos-de-uso"
DEDUPE_KEY = "fake:listing-1:EOD_CLOSE:2026-01-01"


def resolve(external_listing_id: str) -> str:
    """Resolves `external_listing_id` against the configured source."""
    return external_listing_id
'''
    assert scan_python_text(source, path=_MEMORY_PATH) == []


def test_scanner_does_not_flag_clean_english_markdown_with_code_and_links() -> None:
    text = (
        "## Requirement: Quota handling\n\n"
        "See the [terms of use](https://example.com/de/terminos) for details.\n\n"
        "```python\n"
        "de_something = fetch_de_provider()\n"
        "```\n\n"
        "- [x] 1.1 Verify the retry-after window is respected.\n"
    )
    assert scan_markdown_text(text, path=_MEMORY_PATH) == []


def test_scanner_respects_the_intentional_spanish_value_marker() -> None:
    # A fixture like a forbidden-term list legitimately needs to keep a
    # Spanish spelling to test for it; the inline marker is the one
    # sanctioned way to say "this specific line is Spanish on purpose".
    source = 'FORBIDDEN_TERMS = ("cartera",)  # language-scan: intentional-spanish-value\n'
    assert scan_python_text(source, path=_MEMORY_PATH) == []


def test_scanner_ignores_spanish_words_embedded_in_snake_case_identifiers() -> None:
    # `_de_` and `_para_` are substrings here, never standalone tokens, so
    # the word-boundary stopword check must not fire on them.
    source = "fecha_de_captura_para_test = 1\n"
    assert scan_python_text(source, path=_MEMORY_PATH) == []


def test_scanner_flags_spanish_prose_inside_an_fstring_literal() -> None:
    # Python 3.12+ tokenizes an f-string's literal text as FSTRING_MIDDLE,
    # never as a plain STRING token — a real regression this scanner
    # previously missed (`f"Fuente '{source}' no registrada."` in
    # src/market_relay/adapters/registry.py) until FSTRING_MIDDLE was
    # scanned explicitly.
    source = "raise ValueError(f\"Fuente '{source}' no registrada.\")\n"
    findings = scan_python_text(source, path=_MEMORY_PATH)
    assert findings


def test_scanner_flags_spanish_json_object_keys() -> None:
    source = '{\n  "moneda": "EUR",\n  "fuentes": []\n}\n'
    findings = scan_json_text(source, path=_MEMORY_PATH)
    assert findings
    assert any(f.reason == "Spanish JSON key" for f in findings)


def test_scanner_flags_spanish_json_prose_values() -> None:
    source = '{\n  "nota": "Esta fuente todavia no tiene evidencia suficiente"\n}\n'
    findings = scan_json_text(source, path=_MEMORY_PATH)
    assert findings


def test_scanner_respects_the_intentional_spanish_value_marker_in_json() -> None:
    # Standard JSON has no comment syntax, so the marker is embedded
    # directly in the string value it exempts, the same narrow escape
    # hatch as the Python/Markdown scanners, just spelled for JSON.
    source = '{\n  "forbidden_terms": ["cartera (language-scan: intentional-spanish-value)"]\n}\n'
    assert scan_json_text(source, path=_MEMORY_PATH) == []


def test_scanner_does_not_flag_clean_english_json() -> None:
    source = (
        "{\n"
        '  "id": "sap-se-xetr",\n'
        '  "currency": "EUR",\n'
        '  "known_anomalies": ["No adjustment is applied to the raw close."]\n'
        "}\n"
    )
    assert scan_json_text(source, path=_MEMORY_PATH) == []


def test_no_spanish_remnants_in_project_markdown_python_and_json_source() -> None:
    """The actual repository-wide regression check.

    Any hit here means a Markdown doc, a Python comment/docstring/string
    literal, or a JSON key/value was left in Spanish (or reintroduced in
    Spanish) after the repository-wide translation to English.
    """

    findings: list[Finding] = scan_repository()
    assert not findings, "Spanish remnants found:\n" + "\n".join(str(f) for f in findings)


def test_no_spanish_directory_or_file_names_among_project_owned_files() -> None:
    """Regression check for the repository-wide rename to English paths
    (e.g. the former `docs/viabilidad-fuentes/decisiones_fuentes.json`):
    no project-owned directory or file name SHALL be built from Spanish
    words.
    """

    offenders = find_spanish_named_paths()
    assert not offenders, "Spanish-named paths found:\n" + "\n".join(
        str(p.relative_to(REPO_ROOT)) for p in offenders
    )
