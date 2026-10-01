# Trade Date Rules & Settlement Scheduling

**Version:** 1.0  
**Date:** 2026-10-01  
**Status:** Implemented & Verified

---

## Overview

This document describes the complete set of trade date scheduling rules implemented in the PIC (Portfolio Investment Committee) Trade-Plan platform. These rules govern how individual stock orders within a plan are assigned specific execution dates, validate settlement windows, and account for market liquidity, corporate events, and cross-plan commitments.

**Core principle:** Plans must remain executable (not hard-blocked) while maximizing information transparency to the PIC reviewer.

---

## 1. Settlement Window Sanity Check (`_check_settlement_window`)

### Purpose
Validate that a Portfolio Manager's supplied `settlement_date` is realistic for standard Indian equity T+1 settlement.

### Rules

- **Settlement must be after trade:** `settlement_date > trade_date` (at least one trading session between them)
- **Expected gap:** 1 trading session (T+1 is the standard; T+2 and beyond are flagged as unusual)
- **Reasonable window:** Max 5 trading sessions between trade and settlement (beyond that = likely typo)

### Implementation
- Queries real NSE ∩ BSE calendars (via `pandas_market_calendars`)
- Returns **warnings only** — never blocks plan generation (per product guidance on executable plans)
- Warnings surface in the plan output and UI

### Examples
```
✓ trade_date=2026-10-05, settlement_date=2026-10-06  → OK (T+1)
✗ trade_date=2026-10-09, settlement_date=2026-10-05  → Warning: dates reversed
⚠ trade_date=2026-10-05, settlement_date=2026-10-20  → Warning: 11 sessions (unusual)
```

---

## 2. Event-Date Avoidance

### Purpose
Route orders away from known corporate events (earnings, dividends, ex-dates) when the execution window allows, to minimize timing risk.

### Rules

- **Event detection:** Check each ticker's upcoming event (from `data.event_for()`)
- **Avoidance:** If event date falls within the trading-session window, prefer a different session
- **Fallback:** If no alternative session exists, schedule on the event date anyway + flag a warning

### Implementation
- For each order, identify its ticker's next corporate action event
- When assigning a day, exclude the event date from candidates if possible
- Maintains market-impact-aware greedy assignment (don't just move to a worse day)

### Example
```
Order: BUY 10k INFY
Event: INFY ex-dividend 2026-10-05
Window: 2026-10-05 to 2026-10-09 (5 sessions)
Assignment: 2026-10-08 (avoids event, balances load)
```

---

## 3. Market-Impact Cost Model

### Purpose
Estimate the execution cost (in basis points and rupees) for each order based on its size relative to the stock's Average Daily Volume (ADV).

### Formula

```
impact_bps = 15 × √(value_cr / effective_adv_cr)
impact_cost_rupees = (impact_bps / 10,000) × est_value
```

Where:
- **value_cr:** Order size in crores
- **effective_adv_cr:** Min(adv_cr, median_adv_cr) in crores
- **15:** Calibration coefficient (square-root participation model)
- **est_value:** Order value in rupees

### Model Properties
- **Square-root participation:** Standard first-order approximation (not a full execution-cost engine)
- **Dimensionless → ₹:** Converts relative liquidity load into actual cost for PM review
- **Per-order output:** Each order includes `est_impact_bps` and `est_impact_cost`
- **Plan-level output:** Summary includes `est_total_impact_cost` and `est_weighted_impact_bps` (value-weighted across all orders)

### Example
```
Order: BUY ₹100cr worth of stock with ADV=₹500cr
Participation = 100/500 = 0.2
impact_bps = 15 × √0.2 ≈ 6.7 bps
impact_cost ≈ ₹67,000
```

---

## 4. Cross-Plan Awareness (Committed Daily Load)

### Purpose
Account for volume already committed by other approved-and-emailed plans, so the new plan's scheduler doesn't re-book the same days beyond reasonable capacity.

### Rules

- **Scope:** Query all non-rejected stored plans in the database
- **Filter:** Include only plans with status "Approved — sent to Trading" **AND** at least one sent email (execution instruction actually sent)
- **Load calculation:** For each other plan's orders, compute their market-impact cost and accumulate by trade_date
- **New plan's strategy:** Seed the greedy day-assignment with this cross-plan load, so orders land on lighter-loaded days first

### Implementation
- `_committed_daily_load()` queries `db.list_plans()` and `db.list_sent_emails()`
- Uses static universe ADV (simple approximation; doesn't re-load each plan's full dataset)
- Gracefully degrades to zero load if DB is unavailable (fail-open)
- Updated on every plan generation (real-time awareness)

### Example
```
Plan A (already approved + emailed):
  Trade date 2026-10-06: BUY 10k INFY (8 bps impact) + BUY 5k TCS (2 bps) → total 10 bps load

Plan B (being generated):
  Greedy scheduler sees 2026-10-06 already has 10 bps committed
  Steers new orders to 2026-10-05 or 2026-10-07 instead (lighter)
```

---

## 5. Urgency-Weighted Ordering

### Purpose
Prioritize higher-conviction (higher expected-return) orders for first pick of the lightest-loaded execution day, so alpha-rich orders settle sooner.

### Rules

- **Sort key:** Orders sorted by (side, |expected_return|, ticker alphabetically)
  - **Side:** SELLs first (liquidity risk — get proceeds in early)
  - **|expected_return|:** Absolute value of 1-month forecasted return (descending)
  - **Ticker:** Alphabetical tiebreaker
- **Greedy assignment:** Walk sorted orders; each picks the lightest day available, updates that day's load, moves to next

### Example
```
Orders (after sorting by urgency):
1. SELL 5k TCS (highest |return|) → lands on lightest day
2. BUY 10k INFY (+8% return) → lands on next-lightest
3. BUY 8k HCLTECH (+2% return) → lands on next available
```

---

## 6. Dynamic Pending Trades from Approved Plans

### Purpose
Ensure new plans account for cash already committed by approved (and emailed) plans, so:
- Investable cash is realistically reduced
- Sellable shares are realistically reduced
- The UI's "Pending / Unsettled Trades" tab shows the full picture

### Rules

- **Source:** Query all plans in DB with status "Approved — sent to Trading" **AND** at least one sent email
- **Conversion:** Extract each order (ticker, side, shares, price, dates) and format as a pseudo-pending-trade
- **Injection:** Merge approved-plan orders into the `pending_trades` list before cash-flow and sellable-shares calculations
- **Non-blocking:** Never block a plan (keep them executable); this reduces available cash/shares as a side effect

### Implementation

#### In `planner.py` `iter_plan_steps()`:
```python
ds = dict(_get_ds(fund_id))  # shallow copy (don't mutate cache!)
ds["pending_trades"] = (
    list(ds["pending_trades"]) +  # static canned trades
    _augment_pending_trades_from_approved_plans(fund_id)  # orders from DB
)
```

#### In `main.py` `_ds()`:
```python
augmented_ds = dict(ds)
augmented_ds["pending_trades"] = (
    list(ds["pending_trades"]) +
    planner._augment_pending_trades_from_approved_plans(fund_id)
)
return augmented_ds
```

### Trade ID Format
```
PLAN-{PLAN_ID}-{TICKER}
Example: PLAN-E702F7FB-CIPLA
```

### Status Field
```
"Approved (Plan PLAN-E702F7FB)"
```

---

## 7. T+1 Settlement Cycle Validation

### Purpose
Ensure settlement dates respect the standard Indian equity cash-market settlement (T+1).

### Rules

- **Expected:** `settlement_date = trade_date + 1 business day`
- **Tolerance:** 1–5 business days between trade and settlement (beyond = warning)
- **Exclusive window:** The settlement date itself is excluded from the trading-session window (trades must settle by EOD +1 after last trade)

### Calendar Sources
- **NSE calendar:** Indian National Stock Exchange trading sessions
- **BSE calendar:** Bombay Stock Exchange trading sessions
- **Intersection:** Only sessions where both exchanges are open count as valid trading days

---

## 8. Core Scheduling Algorithm (Greedy Load Balancing)

### Overview
Assign each order to a specific trade_date by iterating through orders in urgency order and picking the day with the lowest cumulative impact load.

### Pseudocode
```
1. Get valid trading sessions in window [trade_date, settlement_date)
2. Initialize daily_load = {day: 0.0 for day in sessions}
3. Seed daily_load with committed_daily_load from other approved plans
4. Sort orders by (side, |return|, ticker)
5. For each order:
     a. Identify event date to avoid (if any)
     b. Pick day = argmin(daily_load[d] for d in sessions where d != event)
     c. Assign order["trade_date"] = day
     d. Calculate order["est_impact_bps"] and order["est_impact_cost"]
     e. Update daily_load[day] += impact_bps
6. Return any warnings (e.g., "forced to schedule on event day")
```

---

## 9. Non-Blocking Approach

### Principle
All date-scheduling checks (settlement window, event avoidance, liquidity limits) are **warnings, never hard blocks**. This ensures:
- Large contribution/redemption plans remain executable (per product guidance)
- PIC reviewer sees all constraints, issues a judgment call
- No automatic rejections for "weird" dates or high ADV impact

### Examples
```
✓ Odd settlement gap: warning, plan proceeds
✓ No valid session in window: warning, orders get trade_date = trade_date as-is
✓ Order is 50% of ADV: warning in risk_flags, plan proceeds
```

---

## 10. Output Fields Added to Orders

### Per-order fields (added by scheduler)
```json
{
  "ticker": "INFY",
  "trade_date": "2026-10-06",
  "settlement_date": "2026-10-07",
  "est_impact_bps": 6.7,
  "est_impact_cost": 67000
}
```

### Plan-level summary fields
```json
{
  "summary": {
    "est_total_impact_cost": 250000,
    "est_total_impact_cost_cr": 0.025,
    "est_weighted_impact_bps": 4.9
  }
}
```

---

## 11. Database & Cache Management

### Shared Cache Issue (Fixed)
The global fund dataset (`data_v2.FUNDS_V2[fund_id]`) is a **shared, mutable in-memory cache**. To prevent request-scoped mutations from polluting the cache:

- **`planner.py` `iter_plan_steps()`:** `ds = dict(_get_ds(fund_id))` (shallow copy before modifying)
- **`main.py` `_ds()`:** `augmented_ds = dict(ds)` (same shallow-copy pattern)

This ensures each request gets a fresh `pending_trades` list without accumulating old approvals.

### Database Cleanup
When saving a plan multiple times (e.g., on status updates), explicitly delete all child rows before re-inserting to prevent duplicates:
```python
conn.execute("DELETE FROM plan_orders WHERE plan_id = ?", (plan_id,))
conn.execute("DELETE FROM plan_funding_sources WHERE plan_id = ?", (plan_id,))
conn.execute("DELETE FROM plan_compliance_checks WHERE plan_id = ?", (plan_id,))
conn.execute("DELETE FROM plan_risk_flags WHERE plan_id = ?", (plan_id,))
conn.execute("DELETE FROM plans WHERE plan_id = ?", (plan_id,))
# ... then re-insert
```

---

## 12. Integration Points

### API Endpoints
- **`POST /api/trade-plan`** → calls `planner.generate_plan()` → applies all date rules
- **`POST /api/trade-plan/stream`** → SSE version of above, streams progress + final plan
- **`GET /api/pending-trades`** → calls `main._ds()` → includes approved-plan orders

### Frontend Display
- **Trade Planner tab:** Shows generated plan with order dates, impact costs
- **Trades tab:** Shows static + approved-plan pending trades ("Pending / Unsettled Trades" panel)
- **Plan History tab:** Stores & retrieves full plans with all date/cost fields

---

## 13. Testing & Validation

### Unit Tests
- `tests/test_tax.py` / `tests/test_policy.py`: 17 tests pass (no regressions)

### Regression Test
- `tests/plan_generation_matrix.py`: 120 plans (5 funds × 3 allocation modes)
  - Result: 103/120 executable (85.8%)
  - Baseline unchanged after all date-rule implementations

### Manual Verification
- Cross-plan load accumulation verified with mocked DB
- Event-day avoidance confirmed with real corporate-action dates
- Settlement-window sanity checks validated against NSE/BSE calendars
- Cache-mutation bug reproduced and fixed (no stale state accumulation)

---

## 14. Known Limitations & Future Enhancements

### Current Limitations
1. **Static ADV:** Uses hardcoded universe ADV; no live volume feed
2. **Simple impact model:** Square-root is first-order; not a full execution-cost engine
3. **Day-granular only:** No intraday VWAP/TWAP/participation-rate modeling
4. **No circuit limits:** Doesn't check trading halts or exchange circuit breakers
5. **Single-fund view:** Cross-plan awareness uses static universe ADV, not each plan's own fund dataset

### Possible Enhancements
- **Live ADV feed:** Wire real 20-day rolling volume for more accurate load estimates
- **Execution strategy:** Intraday VWAP/TWAP for large orders
- **Circuit-breaker checks:** Query exchange APIs for halts/limits
- **Multi-fund consolidation:** Pool all funds' approved trades when estimating system-wide liquidity stress
- **Adaptive impact coefficient:** Calibrate the `15 bps` coefficient based on historical slippage data

---

## 15. Maintenance & Troubleshooting

### Resetting to Clean State
```bash
# Reset database (wipes all plans, restores seed data)
cd backend
python scripts/init_db.py --reset

# Restart backend server (clears in-memory cache)
pkill -f "python.*main.py"  # or equiv for your deployment
python -m uvicorn app.main:app --reload
```

### Common Issues

**Duplicates in pending trades:**
- Symptom: Same approved-plan trades appear twice in Trades tab
- Cause: In-memory cache was mutated (pre-fix bug) or React StrictMode in dev (false alarm)
- Fix: (1) Apply the dict() shallow-copy fix, (2) Restart backend, (3) Rebuild frontend

**Orders all landing on same day:**
- Cause: Crossing dates, invalid window, or no NSE/BSE calendars
- Check: `settlement_date > trade_date` and window spans ≥1 trading session

**Impact costs are 0:**
- Cause: ADV lookup failed (ticker not in universe) or est_value is 0
- Check: Ticker exists in `data.UNIVERSE` or fund holdings

---

## References

- **Module:** `backend/app/planner.py` — core scheduling logic
- **API:** `backend/app/main.py` — endpoints using date rules
- **Data:** `backend/app/data.py` / `data_v2.py` — universe + static trades
- **Calendar:** `pandas_market_calendars` — NSE/BSE session validation
- **DB:** `backend/app/db.py` — plan persistence & cleanup

---

## Document Revisions

| Version | Date       | Author  | Changes                                                          |
|---------|------------|---------|------------------------------------------------------------------|
| 1.0     | 2026-10-01 | Claude  | Initial comprehensive documentation of all trade date rules       |

