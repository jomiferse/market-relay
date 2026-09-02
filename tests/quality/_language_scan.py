"""Reusable scanner behind test_language_policy.py.

Finds clear Spanish remnants in project-owned Markdown prose and Python
comments/docstrings/string literals, while staying quiet on URLs, stable
identifiers, and vendor/generated content. Kept separate from the test
module so the detection rules can be unit-tested in isolation from the
full-repository scan.

Detection strategy (deliberately layered to avoid false positives):

1. Spanish diacritics (``áéíóúñ¿¡`` etc.) are checked against *every*
   candidate span (comment, docstring, string literal, or Markdown prose
   line). Real identifiers, enum values, API paths, URLs, and financial
   codes are ASCII by convention in this codebase, so this signal alone is
   already high-precision.
2. A curated list of Spanish stopwords that are vanishingly unlikely to
   appear as a whole word in English prose or inside a technical token
   (``de``, ``para``, ``según``, ...) is matched with word boundaries. Since
   ``\\b`` treats ``_`` as a word character, this does not fire inside
   snake_case identifiers such as ``fecha_de_captura``.
3. Markdown scanning strips fenced/inline code spans and bare URLs before
   applying (1) and (2), so a Spanish word inside a code sample or a URL
   slug is not enough to trip the check on its own.
4. Python scanning skips single-token strings with no whitespace (paths,
   identifiers, error codes, enum-like values) from the stopword check —
   they can still be caught by the diacritics check — so a bare data value
   is not misread as prose.
"""

from __future__ import annotations

import re
import tokenize
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Directories that never hold project-owned prose: VCS metadata, virtual
# envs, tool caches, and build/coverage output.
EXCLUDED_DIR_NAMES = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "__pycache__",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
        ".ipynb_checkpoints",
        "node_modules",
        "dist",
        "build",
        "htmlcov",
        ".cache",
    }
)

_DIACRITICS = re.compile(r"[áéíóúüÁÉÍÓÚÜñÑ¿¡]")

# Whole words that only occur in Spanish, chosen to avoid collisions with
# English words, common abbreviations, or fragments of technical
# identifiers. Word-boundary matching means these must appear as standalone
# tokens, never as a substring of a longer word.
_SPANISH_STOPWORDS = (
    "de",
    "del",
    "la",
    "las",
    "los",
    "el",
    "una",
    "uno",
    "unos",
    "unas",
    "que",
    "para",
    # NOTE: "con" and "sin" are deliberately excluded even though they are
    # Spanish prepositions: both spell real English words/tokens ("con" as
    # in confidence trick, "sin" as in wrongdoing or `math.sin`), so they
    # are not safe as unconditional whole-word signals here. Their
    # accented and multi-word Spanish contexts are still caught by the
    # diacritics check or by the other stopwords around them.
    "sobre",
    "segun",
    "según",
    "cuando",
    "donde",
    "dónde",
    "cada",
    "cualquier",
    "cualquiera",
    "tambien",
    "también",
    "pero",
    "mediante",
    "mientras",
    "aunque",
    "asi",
    "así",
    "aun",
    "aún",
    # NOTE: bare "mas" is excluded — it collides with the acronym "MAS"
    # (e.g. a financial regulator); "más" (with the accent) is caught by
    # the diacritics check instead.
    "más",
    "esta",
    "está",
    "estan",
    "están",
    "sera",
    "será",
    "seran",
    "serán",
    "debe",
    "deben",
    "puede",
    "pueden",
    "fuente",
    "fuentes",
    "proveedor",
    "proveedores",
    "precio",
    "precios",
    "credencial",
    "credenciales",
    "politica",
    "política",
    "instrumento",
    "instrumentos",
    "mercado",
    "mercados",
    "catalogo",
    "catálogo",
    "gobierno",
    # NOTE: bare "ingestion" is excluded — it is spelled identically in
    # English; "ingestión" (with the accent) is caught by the diacritics
    # check instead.
    "ingestión",
    "observacion",
    "observación",
    "observaciones",
    "recuperacion",
    "recuperación",
    "viabilidad",
    "evaluacion",
    "evaluación",
    "evidencia",
    "cotizacion",
    "cotización",
    "cotizaciones",
    "verificar",
    "trabajos",
    "trabajo",
    "cuenta",
)
_STOPWORD_PATTERN = re.compile(
    r"\b(?:" + "|".join(sorted(_SPANISH_STOPWORDS, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)

# Additional Spanish nouns/adjectives that show up as JSON object *keys* (or
# as underscore-joined segments of a key, e.g. `sesiones_ausentes_esperadas`)
# in this codebase's fixtures, but that are unlikely to occur as whole-word
# prose stopwords in the same way as `_SPANISH_STOPWORDS` (which is tuned for
# sentence-level prose, not snake_case identifiers). Kept separate so the
# prose stopword list doesn't grow collision-prone entries (short, generic
# words) purely for the sake of key-name detection.
_SPANISH_KEY_WORDS = frozenset(
    {
        "moneda",
        "monedas",
        "capacidad",
        "capacidades",
        "estado",
        "estados",
        "nota",
        "notas",
        "categoria",
        "categorias",
        "revisor",
        "revisores",
        "alcance",
        "limitacion",
        "paso",
        "pasos",
        "siguiente",
        "previsto",
        "prevista",
        "ausente",
        "ausentes",
        "esperado",
        "esperada",
        "esperados",
        "esperadas",
        "conocido",
        "conocida",
        "conocidos",
        "conocidas",
        "anomalia",
        "anomalias",
        "sesion",
        "sesiones",
        "rol",
        "proxima",
        "proximo",
        "recomendada",
        "recomendado",
        "cuota",
        "cuotas",
        "nombre",
        "nombres",
        "fecha",
        "fechas",
        "rango",
        "bruto",
        "semantica",
        "historico",
        "historica",
        "relevante",
        "relevantes",
    }
)


def _is_spanish_identifier(token: str) -> bool:
    """Returns True if a snake_case/camelCase identifier (a JSON key, or a
    Python variable/function name) is built from Spanish word segments.

    Splits on `_` and on camelCase boundaries, then checks each segment
    against the Spanish prose stopwords and the JSON/identifier-specific
    Spanish word list above. A single matching segment is enough: real
    identifiers in this codebase are English by convention, so
    `estado_global`, `evidenciaUrl`, or `fuentes` should all be flagged the
    same way a Spanish sentence would be.
    """

    segments = re.split(r"[_\W]+", re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", token))
    for segment in segments:
        if not segment:
            continue
        lowered = segment.lower()
        if lowered in _SPANISH_KEY_WORDS:
            return True
        if _STOPWORD_PATTERN.fullmatch(lowered):
            return True
    return False


_URL_PATTERN = re.compile(r"https?://\S+")
# A path or file-name reference embedded in prose — anything from a bare
# `instrument-matrix.md` to a full `docs/source-viability/README.md` —
# stripped before the stopword check so a Spanish word that only occurs as
# a directory/file-name segment (a stable identifier, not prose) doesn't
# trip it. Requires at least one `.` or `/` separator, so it never matches
# an ordinary prose word. The diacritics check still runs on the untouched
# original text, so an actually-accented path would still be caught.
_PATH_LIKE_TOKEN = re.compile(r"\b[\w-]+(?:[./][\w-]+)+\b")
_FENCED_CODE_BLOCK = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE_SPAN = re.compile(r"`[^`\n]*`")
# A "technical token": only word characters, and the punctuation that shows
# up in paths, identifiers, and codes — no whitespace, so it cannot itself
# be a Spanish sentence or phrase.
_TECHNICAL_TOKEN = re.compile(r"^[\w\-./:@+#]*$")


@dataclass(frozen=True)
class Finding:
    path: Path
    line: int
    reason: str
    snippet: str

    def __str__(self) -> str:
        location = self.path.relative_to(REPO_ROOT)
        return f"{location}:{self.line}: {self.reason}: {self.snippet!r}"


def _flag(text: str, *, allow_stopwords: bool) -> str | None:
    """Returns a reason string if `text` looks like Spanish prose, else None.

    The diacritics check runs on `text` as given, so an accented path
    segment is still caught. The stopword check runs on a copy with
    path-like references (e.g. `docs/source-viability/README.md`) and
    backtick-quoted code spans (this codebase's convention for citing an
    identifier or a data/JSON field name inside a docstring or comment,
    e.g. `` `evidencia` ``) stripped out first, so a Spanish word that only
    occurs as a directory/file-name segment or a quoted identifier does
    not trip it.
    """

    if _DIACRITICS.search(text):
        return "Spanish diacritics"
    if allow_stopwords:
        stopword_text = _PATH_LIKE_TOKEN.sub(" ", _INLINE_CODE_SPAN.sub(" ", text))
        if _STOPWORD_PATTERN.search(stopword_text):
            return "Spanish stopword"
    return None


def is_excluded(path: Path) -> bool:
    return any(part in EXCLUDED_DIR_NAMES for part in path.parts) or path.name.endswith(
        (".egg-info", ".lock")
    )


# This module's own Spanish-word stopword list, plus this package's test
# module's deliberately-Spanish positive-detection fixtures, are Spanish by
# design — they are the scanner's own vocabulary and its self-tests, not
# translatable project prose. Excluded from the repository-wide scan only
# (unit tests still exercise them directly via scan_markdown_text /
# scan_python_text on in-memory strings, so detection itself stays tested).
_SELF_TEST_FILES = frozenset(
    {
        Path(__file__).resolve(),
        Path(__file__).resolve().with_name("test_language_policy.py"),
    }
)


def iter_project_files(*, root: Path = REPO_ROOT, suffix: str) -> list[Path]:
    return sorted(
        p
        for p in root.rglob(f"*{suffix}")
        if p.is_file() and not is_excluded(p) and p.resolve() not in _SELF_TEST_FILES
    )


def scan_markdown_text(text: str, *, path: Path = Path("<memory>")) -> list[Finding]:
    stripped = _FENCED_CODE_BLOCK.sub("", text)
    findings: list[Finding] = []
    for lineno, line in enumerate(stripped.splitlines(), start=1):
        prose = _INLINE_CODE_SPAN.sub("", line)
        prose = _URL_PATTERN.sub("", prose)
        if not prose.strip():
            continue
        reason = _flag(prose, allow_stopwords=True)
        if reason:
            findings.append(Finding(path=path, line=lineno, reason=reason, snippet=line.strip()))
    return findings


#: Inline marker for a data value that is intentionally, permanently
#: Spanish — e.g. a forbidden-term fixture that must include the Spanish
#: spelling to actually test for it. Place it as a trailing comment on the
#: same physical line as the value. This is the one sanctioned escape
#: hatch, kept deliberately narrow (line-scoped, not file- or block-scoped)
#: so it can't silently blanket-suppress real prose.
LANGUAGE_SCAN_ALLOW_MARKER = "language-scan: intentional-spanish-value"


# Python 3.12+ (PEP 701) tokenizes an f-string's literal text as one or more
# FSTRING_MIDDLE tokens around the `{expr}` interpolations, never as a
# single STRING token — so an f-string like `f"Fuente '{source}' no
# registrada."` would otherwise sail past a scanner that only looks at
# `tokenize.STRING`. `tokenize` predates PEP 701 on earlier interpreters, so
# this constant is looked up defensively instead of imported by name.
_FSTRING_MIDDLE = getattr(tokenize, "FSTRING_MIDDLE", None)


def scan_python_text(text: str, *, path: Path = Path("<memory>")) -> list[Finding]:
    findings: list[Finding] = []
    lines = text.splitlines(keepends=True)
    try:
        tokens = list(tokenize.generate_tokens(iter(lines).__next__))
    except (tokenize.TokenError, SyntaxError, IndentationError):
        return findings

    for tok in tokens:
        line_text = lines[tok.start[0] - 1] if 0 < tok.start[0] <= len(lines) else ""
        if LANGUAGE_SCAN_ALLOW_MARKER in line_text:
            continue
        if tok.type == tokenize.COMMENT:
            comment = tok.string.lstrip("#").strip()
            reason = _flag(comment, allow_stopwords=True)
            if reason:
                findings.append(
                    Finding(path=path, line=tok.start[0], reason=reason, snippet=tok.string)
                )
        elif tok.type == _FSTRING_MIDDLE:
            # This is always literal f-string text (never an interpolated
            # expression), so it is prose, not a technical value: always
            # allow the stopword check, same as a comment.
            reason = _flag(tok.string, allow_stopwords=True)
            if reason:
                findings.append(
                    Finding(path=path, line=tok.start[0], reason=reason, snippet=tok.string[:120])
                )
        elif tok.type == tokenize.STRING:
            raw = tok.string
            # Strip the quoting/prefix so a technical-token check on the
            # inner value isn't confused by the surrounding syntax.
            inner = raw
            for prefix in ("f", "r", "b", "u", "rb", "br", "fr", "rf"):
                if inner.lower().startswith(prefix) and inner[len(prefix) : len(prefix) + 1] in (
                    "'",
                    '"',
                ):
                    inner = inner[len(prefix) :]
                    break
            inner = inner.strip("'\"")
            is_technical_value = bool(_TECHNICAL_TOKEN.match(inner)) and " " not in inner
            reason = _flag(inner, allow_stopwords=not is_technical_value)
            if reason:
                findings.append(
                    Finding(path=path, line=tok.start[0], reason=reason, snippet=raw[:120])
                )
    return findings


# Matches a `"key": "value"` (or `"key": "value",`) JSON line, capturing the
# key and the (possibly empty) string value. Line-oriented rather than a full
# JSON parse: this codebase's fixtures are hand-formatted with one key per
# line, and a line-based scan keeps findings anchored to a real line number
# the same way the Markdown/Python scanners do.
_JSON_KEY_STRING_VALUE_LINE = re.compile(
    r'^\s*"(?P<key>(?:[^"\\]|\\.)*)"\s*:\s*"(?P<value>(?:[^"\\]|\\.)*)"\s*,?\s*$'
)
# A bare string array element, e.g. an entry of `known_anomalies`.
_JSON_BARE_STRING_LINE = re.compile(r'^\s*"(?P<value>(?:[^"\\]|\\.)*)"\s*,?\s*$')
# A `"key": <non-string>` line (number, bool, null, or the start of a nested
# object/array) — only the key needs checking.
_JSON_KEY_ONLY_LINE = re.compile(r'^\s*"(?P<key>(?:[^"\\]|\\.)*)"\s*:')


def scan_json_text(text: str, *, path: Path = Path("<memory>")) -> list[Finding]:
    """Flags Spanish JSON prose *and* Spanish object keys.

    Unlike Markdown/Python, standard JSON has no comment syntax, so the
    line-scoped `LANGUAGE_SCAN_ALLOW_MARKER` used elsewhere in this module
    is instead recognized as a substring embedded directly in a string
    value (e.g. `"cartera (language-scan: intentional-spanish-value)"`);
    a value containing it is exempted from the prose check, stripped of the
    marker text.
    """

    findings: list[Finding] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        key_value_match = _JSON_KEY_STRING_VALUE_LINE.match(line)
        if key_value_match:
            key = key_value_match.group("key")
            value = key_value_match.group("value")
        else:
            key = None
            bare_match = _JSON_BARE_STRING_LINE.match(line)
            value = bare_match.group("value") if bare_match else None
            if value is None:
                key_only_match = _JSON_KEY_ONLY_LINE.match(line)
                key = key_only_match.group("key") if key_only_match else None

        if key is not None and key != "$comment" and _is_spanish_identifier(key):
            findings.append(
                Finding(
                    path=path,
                    line=lineno,
                    reason="Spanish JSON key",
                    snippet=line.strip(),
                )
            )

        if value is not None:
            if LANGUAGE_SCAN_ALLOW_MARKER in value:
                continue
            is_technical_value = bool(_TECHNICAL_TOKEN.match(value)) and " " not in value
            reason = _flag(value, allow_stopwords=not is_technical_value)
            if reason:
                findings.append(
                    Finding(path=path, line=lineno, reason=reason, snippet=line.strip())
                )
    return findings


def scan_repository() -> list[Finding]:
    findings: list[Finding] = []
    for path in iter_project_files(suffix=".md"):
        findings.extend(scan_markdown_text(path.read_text(encoding="utf-8"), path=path))
    for path in iter_project_files(suffix=".py"):
        findings.extend(scan_python_text(path.read_text(encoding="utf-8"), path=path))
    for path in iter_project_files(suffix=".json"):
        findings.extend(scan_json_text(path.read_text(encoding="utf-8"), path=path))
    return findings


# Extra Spanish words that show up in *directory or file names* in this
# codebase's history but are too generic to belong in `_SPANISH_KEY_WORDS`
# (which is tuned for JSON/identifier key segments) or in `_SPANISH_STOPWORDS`
# (tuned for prose). Kept separate and small on purpose.
_SPANISH_PATH_WORDS = frozenset({"decisiones"})


def _is_spanish_path_segment(segment: str) -> bool:
    if _DIACRITICS.search(segment):
        return True
    return _is_spanish_identifier(segment) or any(
        w in _SPANISH_PATH_WORDS for w in re.split(r"[-_\W]+", segment.lower()) if w
    )


def find_spanish_named_paths(*, root: Path = REPO_ROOT) -> list[Path]:
    """Returns project-owned directories/files whose name (any path segment,
    not just the leaf) is built from Spanish words — a regression check for
    the repository-wide rename to English identifiers and paths (e.g. the
    former `docs/viabilidad-fuentes/decisiones_fuentes.json`).
    """

    offenders: list[Path] = []
    for p in root.rglob("*"):
        if is_excluded(p):
            continue
        try:
            relative = p.relative_to(root)
        except ValueError:
            continue
        for part in relative.parts:
            stem = Path(part).stem
            if _is_spanish_path_segment(stem):
                offenders.append(p)
                break
    return sorted(set(offenders))
