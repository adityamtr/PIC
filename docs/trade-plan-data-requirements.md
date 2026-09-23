# Trade Plan — Data Requirements

## Purpose

This document defines the data required to generate a **trading plan** within the
Portfolio Implementation & Control (PIC) automation tool ("WealthVector"). The tool
automates the middle layer between a Portfolio Manager's (PM) investment intent
and trade execution. It **recommends, it does not decide** — every plan is
reviewed and approved by a PIC associate before execution.

The quality of a generated trading plan is bounded by the quality and
completeness of the data below. Each dataset answers a specific question in the
planning pipeline.

---

## Context

**Traditional process**

```
PM Intent → PIC gathers data → PIC builds spreadsheets → PIC creates plans → PIC validates → Trader executes
```

**AI-assisted process (WealthVector)**

```
PM Intent → Tool gathers data → Tool performs cash flow planning → Tool generates trading plan → Tool recommends → PIC reviews → PIC approves → Trader executes
```

---

## Data Categories

### 1. Investment Intent (input from the PM)

The trigger for the whole plan — what the PM wants to achieve.

| Data element | Description |
|--------------|-------------|
| Target directive | e.g. "increase Technology allocation by $50M", "raise 3% cash" |
| Target weights | Desired end-state portfolio weights / model portfolio |
| Attached constraints | Timing, priority, do-not-trade names |

### 2. Current Positions — *"What do we own right now?"*

| Data element | Description |
|--------------|-------------|
| Holdings | Every security, quantity, market value, portfolio weight |
| Cost basis & unrealized P&L | Needed for tax-aware selling decisions |
| Classification | Asset class / sector / country / issuer (to identify e.g. "Technology") |
| Lot-level detail | Restricted or non-sellable lots |

### 3. Cash & Liquidity — *"What can we actually spend?"*

The core of cash-flow planning. Feeds the forecasting models.

| Data element | Description |
|--------------|-------------|
| Cash balances | Current cash per portfolio, per currency |
| Reserves / minimums | Cash that must be held back (not truly investable) |
| Pending / unsettled trades | Cash already committed but not yet moved |
| Settlement calendar | When inflows/outflows land (T+1, T+2 conventions) |
| Receivables / payables | Dividends, coupons, fees due in/out |
| Corporate actions | Dividends, splits, mergers, maturities affecting cash & holdings |

### 4. Investable Universe & Prices — *"What can we buy/sell, and at what price?"*

| Data element | Description |
|--------------|-------------|
| Eligible universe | Approved / eligible securities list |
| Market prices | Current prices, lot / round-lot sizing rules |
| Liquidity data | Average daily volume, bid/ask spreads (for realistic order sizing) |

### 5. Constraints & Rules — *"What are we NOT allowed to do?"*

The domain layer. Becomes the constraint set in the optimization engine.

| Data element | Description |
|--------------|-------------|
| Compliance limits | '40 Act rules, prospectus limits, sector / issuer / single-name caps |
| Mandate restrictions | Client IPS restrictions, ESG or exclusion lists |
| Trading dependencies | Ordering rules (e.g. must sell X before buying Y) |
| Tax constraints | Wash-sale rules, tax-lot considerations |

### 6. Market & Event Context — *"When is a bad time to execute?"*

| Data element | Description |
|--------------|-------------|
| Event calendar | Upcoming earnings, macro events, market-sensitive news |
| Volatility signals | Signals that flag execution-timing risk |

---

## How the Data Feeds the Pipeline

| Data category | Feeds… | Produces |
|---------------|--------|----------|
| Investment Intent | Whole plan | Target |
| Positions + Cash/Liquidity | Forecasting models (SARIMA / LSTM / TFT) | Investable amount |
| Universe + Prices | Optimizer | Candidate orders |
| Constraints / Compliance | Optimizer constraints | Feasible plan |
| Market / Event context | Risk detection | Timing / exception flags |

The optimization engine takes the intent (e.g. "$50M into Tech"), subtracts what
is not truly available (reserves, unsettled commitments), respects the caps and
constraints, and emits an **ordered set of share-level buy/sell orders, funding
sources, and risk flags** — the trading plan the PIC associate then reviews.

---

## Open Decisions (to confirm before build)

1. **Real vs. mocked data** — for a POC, positions / cash / settlements can be
   stubbed with synthetic data while the intelligence focuses on forecasting and
   optimization.
2. **Granularity** — single portfolio or a book of portfolios?
3. **Currency** — single-currency or multi-currency support?

---

## Source

Derived from *The Minimalist — Segment 1* write-up (Team: The Minimalist,
Category: Capital Group) and the PIC workflow diagram.
