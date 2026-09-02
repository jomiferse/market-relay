# Evaluation of free price providers by asset class (tasks.md 3.3)

**Aggregate result: no evaluated provider reaches `GO`.** All
remain `NO-GO` or `UNRESOLVED` and none is enabled in
`Settings.enabled_sources` (only `"fake"`) nor has an `APPROVED`
`SourcePolicyDecision` recorded — verified by `tests/unit/test_source_viability_gate.py`.
Review date: 2026-09-02. Next review recommended: 2027-03-02.

Full structured data, with evidence per capability:
[`tests/fixtures/source_viability/source_decisions.json`](../../tests/fixtures/source_viability/source_decisions.json).

The central distinction of this document — and the reason no
provider passes — is that **technical viability (`RETRIEVE` accessible) does not
imply storage or redistribution permission**. MarketRelay's model
always implies all three things at once: retrieving, retaining in its
own database, and republishing to Holdria through its API — which
is, in terms of most of these sources, a commercial redistribution
to a third party, not "internal use".

## Stocks and ETFs listed on Xetra

### Deutsche Börse Public Dataset (AWS Open Data)

- **Verdict: `NO-GO`.**
- Source: <https://registry.opendata.aws/deutsche-boerse-pds/>.
- `RETRIEVE`: `GO` — public dataset on S3, 1-minute aggregates of
  Xetra/Eurex, no authentication.
- `STORE` / `DISPLAY` / `RETAIN`: `NO-GO` — licensed under **Non-Commercial
  (NC)** terms: "copy, distribute, display, and perform the work
  ... only for non-commercial purposes". Republishing to Holdria, a
  commercial product, does not fit that use.
- `REDISTRIBUTE`: `NO-GO` — any use other than trading in the market
  itself requires a paid license (MDDA); see
  <https://www.mds.deutsche-boerse.com/resource/blob/3134034/dac167f9f376e95323f12c42db14e173/data/Market-Data-Policy-Guidelines-and-FAQ_V2_2.pdf>.
- Reconsider only if Deutsche Börse Group explicitly offers a
  commercial license (MDDA) for this use.

### Generic aggregated providers (Alpha Vantage, Twelve Data)

- **Verdict: `NO-GO`** at the free tier for both.
- Alpha Vantage (<https://www.alphavantage.co/terms_of_service/>): `RETRIEVE`
  `GO` with a free key (documented request/day limit); commercial
  redistribution and exchange-licensed data require "separate
  incorporation and licensing" per the provider's own documentation —
  `REDISTRIBUTE` `NO-GO`.
- Twelve Data (<https://twelvedata.com/terms>,
  <https://support.twelvedata.com/en/articles/5332349-commercial-and-personal-usage>):
  the free plan allows storage "solely for internal use", but showing
  data to third parties or redistributing it requires a redistribution
  add-on or a Venture (business) plan or higher — `REDISTRIBUTE` `NO-GO` on the
  free plan.
- Neither is specific to Xetra/Euronext; they are evaluated as
  generic multi-market candidates, not as a primary source for
  European equities.

## Stocks and ETFs listed on Euronext

### Euronext Data Shop (free EOD)

- **Verdict: `NO-GO`** (with `RETRIEVE`, `STORE`, and `DISPLAY` at `UNRESOLVED` and `REDISTRIBUTE` at explicit `NO-GO`; the worst capability determines the overall verdict).
- Source: <https://www.euronext.com/en/data/end-day-index-data>,
  <https://www.euronext.com/en/data/pricing-specs-agreements/data-agreements-types>.
- Free EOD access is described as for "internal use"; commercial
  use or redistribution to a third party requires a signed
  **Euronext Market Data Agreement (EMDA)** — MarketRelay does not have one.
- Next step, if Euronext instrument volume justifies it:
  contact `databyeuronext@euronext.com` to negotiate an EMDA.

## European funds (unlisted UCITS)

No generic free provider was identified that publishes NAV of
unlisted UCITS funds with clear storage and redistribution
permissions. Candidate scraping sources for fund fact sheets
(justETF, management company sites) are evaluated in `scraping-evaluation.md` and
remain `UNRESOLVED`. This leaves the "European fund" asset class without
an approved automatable source in this wave — see the risk already anticipated
in `design.md` § "Free sources may change coverage or limits".

## Crypto assets / EUR

### CoinGecko (free/demo API)

- **Verdict: `NO-GO`.**
- Source: <https://www.coingecko.com/en/api_terms>.
- `RETRIEVE` / `STORE` (with cache ≤24h) / `DISPLAY`: `GO`, with mandatory
  "Powered by CoinGecko" attribution.
- `REDISTRIBUTE`: `NO-GO` — "You are not permitted to sell, rent, lease,
  sub-license, re-distribute or syndicate access to the CoinGecko API or
  part thereof" without a separate Enterprise agreement.
- `RETAIN`: `NO-GO` long-term — stored data must be deleted
  when the agreement ends and the cache must be refreshed every 24h.

### Kraken (public market REST API)

- **Verdict: `UNRESOLVED`.**
- Source: <https://www.kraken.com/legal/global-terms>.
- Kraken's general terms expressly prohibit "web scraping, web
  harvesting, or data extraction methods"; within the scope of this
  review, no separate public API policy
  (docs.kraken.com/api) was found that explicitly excludes its own market
  endpoints from that general prohibition.
- Next step: request written clarification from Kraken before
  reconsidering.

### Bitstamp (public market REST API)

- **Verdict: `UNRESOLVED`.**
- Source: <https://www.bitstamp.net/api/>.
- `RETRIEVE`: `GO` — public endpoints, no authentication.
- The remaining capabilities are `UNRESOLVED`: Bitstamp explicitly requires
  contacting `partners@bitstamp.net` and signing a "commercial use Data License
  Agreement" to incorporate or redistribute its data for
  commercial purposes — an agreement MarketRelay does not have.

## Operational conclusion

Until an explicit commercial agreement is signed (Euronext EMDA, Bitstamp
Data License Agreement) or Kraken's ambiguities are resolved in writing,
**the deterministic `fake` provider remains the only active adapter**,
as required by `specs/source-governance/spec.md` § "Safe test
adapters" and verified by `tests/unit/test_config.py::test_settings_default_to_sqlite_and_fake_source_only`.
