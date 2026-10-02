# Data v2: real source values vs curated defaults

This document explains what is genuinely sourced from the real feed in [backend/app/data_v2.py](../backend/app/data_v2.py) and what has been filled with curated values so that the app continues to work with the same contract as the dummy source in [backend/app/data.py](../backend/app/data.py).

## Source hierarchy

The V2 model uses the following real sources first:

- XLSX disclosure files under `data/raw/Funds Monthly Portfolio Disclosure(18 funds)/current/`
- Latest price snapshot from `data/processed/final/stock_macro_monthly_target.csv`
- `xlsx_parser` logic to convert raw disclosure rows into normalized holdings dictionaries

Anything not present in the raw feed is handled with curated defaults using fund strategy logic, not arbitrary placeholder numbers.

A third pass, [compute_risk_return_metrics.py](../backend/scripts/compute_risk_return_metrics.py), reuses the *full* historical series in `stock_macro_monthly_target.csv` (not just the latest snapshot) plus the real current holding weights from `data_v2.build_datasets_from_source()` to compute **derived** risk/return metrics — see below.

---

## Real values used in every fund

These values are imported directly from the real data sources:

- `holdings_list`
- `security_name` / fund name
- `industry` / sector mapping
- `quantity` and `market_value` from the disclosure file
- `percentage_nav` from the fund file
- `isin`
- `price` from the latest CSV snapshot by ISIN
- ticker symbol resolution using the CSV data when available

These are not fabricated; they are the actual values used as the base for the V2 dataset.

---

## Curated values intentionally added

These fields are not available in the raw disclosure data, so they are filled with realistic defaults aligned to the fund’s strategy:

- `cash_total` and `cash` reserves
- `fund_expense.expense_ratio`, `annual_expense`, `daily_accrual`, `monthly_accrual`, and expense components
- `lock_in_expiry` and `lock_in_reason` for strategic holding restrictions
- `locked_shares` and `sellable_shares`
- `event_calendar` entries
- `group` fallback when only sector/industry is available
- `fund_manager`, `inception`, and some metadata fields when the source feed does not provide them

These values are curated to match a realistic portfolio-management playbook rather than being random placeholders.

---

## Derived values: risk/return metrics (neither real nor curated — computed)

[compute_risk_return_metrics.py](../backend/scripts/compute_risk_return_metrics.py) adds a
third category alongside "real" and "curated": metrics that are **calculated**
from real inputs rather than sourced or hand-picked. Per
[docs/nav-risk-return-metrics.md](nav-risk-return-metrics.md), it writes:

- `data/processed/final/stock_risk_return_metrics.csv` — one row per ISIN
  (404 stocks with ≥12 months of history): 1M/3M/6M return, annualized return,
  annualized volatility, max drawdown, Sharpe, Sortino. Computed directly from
  the real monthly adjusted-close series in `stock_macro_monthly_target.csv`.
- `data/processed/final/fund_risk_return_metrics.csv` — one row per fund
  (all 5 `FUND_SPECS_V2` funds). There is no ingested fund NAV history
  (`funds.nav` is a single current snapshot), so the `annualized_return` /
  `annualized_volatility` / drawdown / Sharpe / Sortino columns here are a
  **synthetic** series: each fund's *real* current holding weights
  (`h["weight"]` from `data_v2`, 93–99% of AUM mapped per fund) are applied to
  the historical stock return panel (`r_portfolio,t = Σ w_i · r_i,t`), then the
  same metrics are computed on that reconstructed series.

  Alongside that, `strategy_return_low/high` and `strategy_volatility_low/high`
  are derived from that *same* synthetic series, not hand-picked: they are the
  20th/80th percentile of annualized return/volatility across rolling 3-year
  (36-month) windows of the fund's own history (`strategy_range_source =
  rolling_percentile`) — "the range this fund's own current-weight book has
  actually landed in historically", computed by the same script, so it can't
  silently drift away from what the "current" full-history point measures. A
  fund with too little history for rolling windows falls back to a band sized
  off `risk_grade` around its single full-history point
  (`strategy_range_source = risk_grade_fallback`). This is the default range
  for the risk/return slider in the UI and the default `sigma_max` /
  `mu_target` constraint the optimizer uses — a PIC associate can still drag
  the slider past it. An earlier version of this band was a hand-picked
  per-fund constant (`data_v2.FUND_STRATEGY_RISK_RANGE`), which every fund's
  volatility ended up exceeding since the guess was never checked against the
  actual data; it has been removed in favor of this computed band.

Caveats: the source data is monthly (so "1M/3M/6M" means 1/3/6 monthly bars,
not trading days), and the risk-free rate (6.5%) is an assumption, not an
ingested value.

---

## Fund-by-fund breakdown

### 1) HDFC-FLEXICAP-DG

Real values used:
- Holdings from `INF179K01UT0_HDFC Flexi Cap Fund.xlsx`
- Price data from `stock_macro_monthly_target.csv` mapped by ISIN
- Market value, quantity, percent-of-nav from the disclosure file

Curated values used:
- Cash buffer: 6.0% of AUM
- Expense ratio: 0.72%
- Lock-ins: `POWERGRID`, `LT`, `ITC`, `BHARTIARTL`
- Event calendar: dividend / earnings entries aligned to large-cap and flexi-cap core holdings

### 2) ICICIPRU-LARGECAP-DG

Real values used:
- Holdings from `INF109K016L0_ICICI Prudential Large Cap Fund.xlsx`
- Price snapshot by ISIN
- Sector and quantity data from raw disclosure

Curated values used:
- Cash buffer: 3.5% of AUM
- Expense ratio: 0.68%
- Lock-ins: `LT`, `ICICIBANK`, `RELIANCE`
- Event calendar: results / dividend events for core names

### 3) SBI-NIFTY50-ETF-DG

Real values used:
- Holdings from `INF200KA1FS1_SBI Nifty 50 ETF.xlsx`
- ISIN-based price mapping from final price dataset
- Index holdings and stake weight from the ETF disclosure file

Curated values used:
- Cash buffer: 1.0% of AUM
- Expense ratio: 0.18%
- Lock-ins: a light set for index-core names like `RELIANCE`, `TCS`, `INFY`, `HDFCBANK`
- Event calendar: standard index constituent events

### 4) HDFC-RETIREMENT-EQUITY-DG

Real values used:
- Holdings from `INF179KB1MF0_HDFC Retirement Fund - Equity Plan.xlsx`
- Prices and stock mapping by ISIN
- Raw sector and quantity exposures

Curated values used:
- Cash buffer: 7.5% of AUM
- Expense ratio: 0.79%
- Lock-ins: `RELIANCE`, `HDFCBANK`, `ICICIBANK`, `INFY`
- Event calendar: long-horizon quality holdings with dividend and earnings markers

### 5) KOTAK-LARGEMIDCAP-DG

Real values used:
- Holdings from `INF174K01LF9_Kotak Large & Mid Cap Fund.xlsx`
- Price lookup and stock mapping by ISIN
- Raw industry / quantity / market-value data from the disclosure file

Curated values used:
- Cash buffer: 5.0% of AUM
- Expense ratio: 0.74%
- Lock-ins: `LT`, `SBIN`, `MARUTI`, `BHARTIARTL`
- Event calendar: balance of index and quality-pick corporate events

---

## Why this is the right split

This split keeps the real investment data intact while filling the missing operational fields that the application expects:

- Real feed = portfolio exposure, names, sectors, quantity, price, and weighting
- Curated values = cash, expense, lock-ins, events, and app-level operational metadata
- Derived values = risk/return metrics computed from the real feed (stock-level) or from real weights applied to real price history (fund-level, synthetic)

That means the V2 source remains faithful to the underlying disclosure while still satisfying the same contract used by the dummy dataset in [backend/app/data.py](../backend/app/data.py).
