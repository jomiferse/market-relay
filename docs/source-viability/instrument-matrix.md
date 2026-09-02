# Representative instrument matrix (tasks.md 3.1)

Reproducible source: [`tests/fixtures/source_viability/instrument_matrix.json`](../../tests/fixtures/source_viability/instrument_matrix.json).
This document is the narrative reading of that file; in case of any
discrepancy, the JSON is the canonical reference and `tests/unit/test_source_viability_fixtures.py`
keeps it valid.

It contains no credentials or personal data: all identifiers
(ISIN, ticker, MIC) are public reference data for listed instruments,
verified against public sources on 2026-09-02 (see links in each
row). The FIGI field is deliberately left unresolved — see
`openfigi-evaluation.md` — so as not to set a value unverified by this
review.

## Stocks — Xetra

| Instrument | ISIN | MIC / venue | Ticker | Currency |
|---|---|---|---|---|
| SAP SE | `DE0007164600` | XETR — Deutsche Börse Xetra | `SAP` | EUR |
| Siemens AG | `DE0007236101` | XETR — Deutsche Börse Xetra | `SIE` | EUR |

- **Raw `close` semantics**: closing price of Xetra's closing
  auction, unadjusted for dividends or splits (specs/market-observations §
  "Raw value with no implicit adjustments").
- **Historical range**: both have traded on Xetra since well before
  any evaluated candidate source; the real limit is imposed by each source,
  not the instrument (e.g., Deutsche Börse's Public Dataset on AWS only
  covers from 2018).
- **Expected missing sessions**: weekends and holidays on the
  Xetra/FWB calendar (Christmas, New Year, Good Friday, and December 24/31
  when they fall on a weekday, per the calendar Deutsche Börse
  publishes annually).
- **Quotas**: see `price-providers-evaluation.md` — no
  evaluated free source reaches `GO` to redistribute these prices to Holdria.
- **Known anomalies**: Deutsche Börse's Public Dataset aggregates in
  1-minute bars and does not directly publish an official EOD `close` (it must
  be derived from the last bar); Siemens has had historical spin-offs
  (Siemens Energy, Siemens Healthineers) that are not reflected in the raw
  `close` and are out of scope for the MVP.

## Stocks — Euronext

| Instrument | ISIN | MIC / venue | Ticker | Currency |
|---|---|---|---|---|
| LVMH Moët Hennessy Louis Vuitton SE | `FR0000121014` | XPAR — Euronext Paris | `MC` | EUR |
| ASML Holding N.V. | `NL0010273215` | XAMS — Euronext Amsterdam | `ASML` | EUR |

- **Raw `close` semantics**: official closing price of each
  Euronext market's closing auction mechanism, unadjusted.
- **Historical range**: both have traded since well before
  any evaluated candidate source.
- **Expected missing sessions**: Euronext groups several
  national markets (XPAR, XAMS, XBRU, XLIS) under a single group, but with
  local holiday calendars that can differ on specific dates —
  do not assume a single Euronext calendar.
- **Quotas**: Euronext's free EOD access is described as for "internal
  use"; redistributing to Holdria would require a Euronext Market Data
  Agreement (EMDA), which does not exist today — see `price-providers-evaluation.md`.
- **Known anomalies**: ASML also trades on Nasdaq in USD; resolving its
  identity without filtering by MIC and currency can silently mix the
  EUR line on XAMS with the USD line on Nasdaq (specs/instrument-catalog §
  "Ambiguous EUR match").

## UCITS ETFs

| Instrument | ISIN | MIC / venue | Ticker | Currency |
|---|---|---|---|---|
| iShares Core MSCI World UCITS ETF USD (Acc) | `IE00B4L5Y983` | XETR — Deutsche Börse Xetra | `EUNL` | EUR |
| Vanguard FTSE All-World UCITS ETF USD (Acc) | `IE00BK5BQT80` | XETR — Deutsche Börse Xetra | `VWCE` | EUR |

- **Raw `close` semantics**: Xetra closing price for the EUR-denominated
  trading line; the trading currency (EUR on Xetra) is independent
  of the underlying fund's base currency (USD in both cases).
- **Historical range**: iShares Core MSCI World was listed on 2009-09-25;
  Vanguard FTSE All-World launched on 2019-07-23 (dates per
  public issuer documentation); the real recoverable range depends on each source.
- **Expected missing sessions**: Xetra's holiday calendar; also,
  an ETF may not trade on a given day due to lack of liquidity without being a
  holiday — a market-absent session, not a source-absent one.
- **Quotas**: same candidate sources and same limitations as the
  Xetra stocks.
- **Known anomalies**: the same ISIN trades under **different tickers
  depending on the market** (e.g., `IE00B4L5Y983` trades as `SWDA` on the London
  Stock Exchange and as `EUNL` on Xetra) — the textbook case of
  specs/instrument-catalog § "ISIN with multiple listings". Both ETFs are
  accumulating (Acc): they do not distribute visible dividend cash outflows,
  which can be mistaken for the absence of corporate actions when comparing
  price series.

## European funds (unlisted UCITS)

| Instrument | ISIN | MIC / venue | Ticker | Currency |
|---|---|---|---|---|
| Amundi Funds Euro Corporate Bond - A EUR | `LU0119099819` | — (not exchange-listed; subscription/redemption at NAV via Amundi Luxembourg SA) | — | EUR |
| Amundi Funds Euro Government Bond - A EUR | `LU0518421895` | — (not exchange-listed; subscription/redemption at NAV via Amundi Luxembourg SA) | — | EUR |

Both are real sub-funds, verified directly against their official Key
Investor Information Document (KIID) published by the management company at
<https://www.amundi.com>: SICAV **Amundi Funds**, domiciled in Luxembourg,
regulated by the CSSF, with Amundi Luxembourg SA as Management Company.
Share class `A` is accumulating; both sub-funds also have
a distributing class `D` with a different ISIN (`LU0119100179`
and `LU0518421978` respectively) — always resolve by the exact ISIN of
the class, not by the sub-fund name. The Corporate Bond KIID is
current as of June 9, 2022 (sub-fund and class launched on 1999-02-01); the
Government Bond one is current as of February 11, 2022 (sub-fund and class
launched on 2010-07-01). Neither fund is exchange-listed: they have no
MIC or exchange ticker, and this matrix deliberately leaves them
blank rather than fabricating them.

- **Raw `close` semantics**: an open-ended unlisted fund has no market
  `close`; the relevant EOD observation is the **NAV (Net Asset
  Value)** per share, which MarketRelay treats as the raw `close` for this
  asset class (design.md § "Different strategies by frequency").
- **NAV and publication window**: both funds' KIID states that
  shares are subscribed/redeemed "on any dealing day"
  per the prospectus, at the NAV corresponding to that day; the
  "latest net asset value" is published at <https://www.amundi.com>. The KIID
  does not detail the exact cutoff time or the T+n publication lag —
  that specific figure only appears in the full UCITS prospectus, not
  reviewed in this wave; no NAV value or specific lag not directly
  verified is claimed here.
- **Historical range**: depends entirely on each management company; there is no
  single, uniform public source of NAV history for unlisted European
  funds equivalent to a regulated market.
- **Expected missing sessions**: days that are not dealing days (Luxembourg
  holidays and the fund's own calendar, incidents at the
  administrator/depositary CACEIS Bank). The
  `WAITING_FOR_PUBLICATION` state (specs/market-observations) applies while
  the day's NAV has not yet been published.
- **Quotas**: no candidate source evaluated in 3.3 generically,
  freely, and with clear permissions covers the NAV of Amundi's unlisted
  funds; see `price-providers-evaluation.md`.
- **Known anomalies**: the catalog must support the absence of MIC and
  exchange ticker without fabricating them, just as it already supports the absence
  of ISIN for crypto assets (specs/instrument-catalog § "Crypto asset without ISIN or
  MIC" describes the same optional-field pattern); each sub-fund has
  several share classes with a different ISIN for the same strategy, so
  resolve by class ISIN, not by sub-fund name.

## Crypto assets / EUR

| Instrument | ISIN | MIC / venue | Ticker | Currency |
|---|---|---|---|---|
| Bitcoin / Euro | — | Crypto spot market (venue depends on the adapter) | `BTC/EUR` | EUR |
| Ether / Euro | — | Crypto spot market (venue depends on the adapter) | `ETH/EUR` | EUR |

- **Raw `close` semantics**: there is no regulated market close;
  EOD `close` is defined by MarketRelay's own convention as the last
  price of the 24/7 UTC session (e.g., cutoff at 00:00 UTC). This
  convention SHALL be documented and kept stable so as not to break
  historical series if it changes in the future.
- **Historical range**: depends on the chosen venue/adapter.
- **Expected missing sessions**: in theory none (24/7 market); in
  practice gaps can exist due to exchange maintenance or
  source interruptions, which SHALL be treated as a **source**-absent
  session, never as a **market**-absent session
  (specs/market-data-ingestion).
- **Quotas**: see `price-providers-evaluation.md` —
  `coingecko_free_demo` (`NO-GO` for redistribution), `kraken_public_rest_api`
  and `bitstamp_public_rest_api` (`UNRESOLVED`).
- **Known anomalies**: the BTC/EUR and ETH/EUR price can differ by several
  basis points between exchanges due to liquidity fragmentation
  (specs/market-observations § "Two approved sources differ" applies
  directly); network events (hard forks, consensus changes) can
  produce anomalous price movements that are not source errors.
