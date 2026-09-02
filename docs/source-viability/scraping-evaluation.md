# Evaluation of scraping candidates (tasks.md 3.4)

**Aggregate result: no scraping candidate reaches `GO`.** All
remain `NO-GO` or `UNRESOLVED` and none is implemented as a
real adapter in this wave. Review date: 2026-09-02. Next review
recommended: 2027-03-02, or sooner if the terms or `robots.txt`
published by any of these sites change.

Full structured data:
[`tests/fixtures/source_viability/source_decisions.json`](../../tests/fixtures/source_viability/source_decisions.json)
(`source_id` with `scraping_` prefix).

## Evaluation criteria

For each scraping candidate, three types of independent public
evidence were sought, following the mandate of task 3.4:

1. **Published terms** (terms of use / general conditions) that
   explicitly mention automated extraction, reuse, or
   redistribution of data.
2. **`robots.txt`** of the domain, as a technical signal — never as a substitute
   for explicit legal authorization.
3. **Known stability and operating limits** (whether the site itself
   publicly documents or tolerates automated access).

If any of the three is missing, or if they are contradictory, the candidate is
marked `NO-GO` (when there is an explicit prohibition) or `UNRESOLVED` (when
sufficient evidence is missing) and remains disabled. In no case is
permission inferred from the fact that a page is technically accessible
(design.md § Non-Goals: "Infer licenses from an API or page
being publicly accessible").

## investing.com — `NO-GO`

- Terms: <https://cdn.investing.com/about-us/terms_and_conditions.pdf>.
- Explicit, unambiguous prohibition: "employing any automated system or
  software to extract data or content from this website for any purpose is
  prohibited", and further "It is prohibited to use, store, reproduce, display,
  modify, transmit or distribute the data ... without the explicit prior
  written permission of Fusion Media and/or the data provider."
- This blocks `RETRIEVE` from the very first step, before even considering
  storage or redistribution.
- **Permanently discarded** unless explicit written permission is obtained from
  Fusion Media, considered highly unlikely given the company's public
  track record of actively enforcing this clause against third parties.

## Stooq — `NO-GO`

- Evidence: `robots.txt` at <https://stooq.com/robots.txt>, which denies
  `/` to every user agent except `Googlebot` and `Bingbot`, with no exception
  for other agents.
- Within the scope of this review, no published terms of use were found
  that explicitly authorize automated retrieval by third parties
  despite that general `robots.txt` denial.
- Although many third-party tools have historically downloaded Stooq's CSV
  files with no apparent block, **the technical accessibility of those URLs does
  not equal authorization** (design.md § Non-Goals), and the signal published by
  the site itself (`robots.txt: Disallow: /`) points in the opposite
  direction.
- Remains discarded unless a published terms of use exists that
  explicitly contradicts that denial for third-party automated
  use.

## justETF — `UNRESOLVED`

- `robots.txt` (<https://www.justetf.com/robots.txt>) only denies
  specific paths (`/servlet/`, `/link/`, search/watchlist parameters with
  `_wicket`); it does not deny ETF fact sheets themselves. This is only a
  permissive technical signal, not legal authorization.
- justETF GmbH's general terms and conditions were found at
  <https://www.justetf.com/documents/justETF_general_terms_and_conditions.pdf>,
  but were not reviewed line by line within the scope of this wave — it cannot
  be confirmed nor ruled out with sufficient evidence whether third-party
  automated use to redistribute fact-sheet data (NAV, ISIN,
  TER) is permitted.
- **Remains disabled** until that document is reviewed in full and,
  if necessary, justETF GmbH is consulted in writing.

## Börse Frankfurt / Deutsche Börse (web fact sheets) — `UNRESOLVED`

- `www.boerse-frankfurt.de/robots.txt` redirects (308) to
  `live.deutsche-boerse.com/robots.txt`, whose observed content only
  references a `sitemap.xml` with no clear denial rules for instrument
  fact sheets — again, a permissive technical signal with no legal value
  on its own.
- Within the scope of this review, no terms of use ("Nutzungsbedingungen")
  specific to the web fact-sheet content authorizing its extraction and
  redistribution by third parties were found.
  This is distinct from Deutsche Börse's Public Dataset on AWS, already evaluated
  separately in `price-providers-evaluation.md` (explicit
  Non-Commercial license, `NO-GO` for this use).
- **Remains disabled** until those terms of use are located and reviewed and,
  if necessary, Deutsche Börse AG is consulted in writing.

## Why no scraper is implemented in this wave

`specs/source-governance/spec.md` requires that no source be enabled
without `APPROVED` evidence; `design.md` § "Scraping may breach
terms or break" sets the default mitigation as "disabled
unless favorable evidence, review of `robots.txt` and terms, conservative
limits, and contract tests". No candidate on this list meets
that threshold today:

- `investing.com` and `stooq` have explicit evidence **against**.
- `justetf` and `boerse-frankfurt` have **insufficient** evidence, not
  favorable evidence.

Consequently, no scraper code is written for any of these
candidates, and `tests/unit/test_source_viability_gate.py` verifies that
`Settings.enabled_sources` remains only `("fake",)`.
