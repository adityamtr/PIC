# Data v2: real source values vs curated defaults

This document explains what is genuinely sourced from the real feed in [backend/app/data_v2.py](../backend/app/data_v2.py) and what has been filled with curated values so that the app continues to work with the same contract as the dummy source in [backend/app/data.py](../backend/app/data.py).

## Source hierarchy

The V2 model uses the following real sources first:

- XLSX disclosure files under `data/raw/Funds Monthly Portfolio Disclosure(18 funds)/current/`
- Latest price snapshot from `data/processed/final/stock_macro_monthly_target.csv`
- `xlsx_parser` logic to convert raw disclosure rows into normalized holdings dictionaries

Anything not present in the raw feed is handled with curated defaults using fund strategy logic, not arbitrary placeholder numbers.

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

That means the V2 source remains faithful to the underlying disclosure while still satisfying the same contract used by the dummy dataset in [backend/app/data.py](../backend/app/data.py).
