# Final Taxation Rules

**Version:** 1.2
**Date:** 2026-10-02
**Status:** Implemented & Verified

---

## Overview

This document describes the complete set of taxation rules implemented in the
PIC (Portfolio Investment Committee) Trade-Plan platform. These rules govern
how capital-gains tax, transaction charges, and cross-plan tax state are
computed for every generated plan.

**Core principle:** Tax figures should be realistic enough to drive genuinely
useful decisions (preferring low-tax exits, harvesting losses) while staying
honest about what's real statutory law vs. a deliberate modeling choice. See
[taxation-model.md](taxation-model.md) for the narrative explanation and the
fund-level exemption caveat; this document is the rules reference.

---

## 1. The Fund-Level Caveat (Read This First)

### Rule
Real Indian mutual funds are **exempt from capital-gains tax at the fund
level** under Section 10(23D) of the Income Tax Act — tax liability shifts to
the investor only on redemption of fund units, not when the fund itself
trades a stock.

### Why it's modeled anyway
The capital-gains layer here is a **deliberate PMS/taxable-account framing**,
not an oversight. It demonstrates a genuinely useful decision pattern —
preferring low-tax exits and harvesting losses — that a fund manager
evaluating "which holdings are more/less suitable to sell" would still care
about in an advisory or non-exempt context. **STT, stamp duty, brokerage, and
exchange charges are real regardless of this exemption** and apply on every
buy and sell either way.

---

## 2. Statutory & Effective Rates (FY 2025-26)

### Source of truth
[data/processed/tax/tax_rates.json](../data/processed/tax/tax_rates.json),
loaded by `tax_rules.py` with embedded fallbacks, and mirrored into the
`tax_rules` DB table by `init_db.py` (DB wins if present). A future budget
change is a config edit, not a code change.

### Rules

| Parameter | Value | Constant |
|---|---|---|
| STCG statutory rate | 20% (holding < 12 months) | `STCG_STATUTORY_RATE` |
| LTCG statutory rate | 12.5% (holding ≥ 12 months) | `LTCG_STATUTORY_RATE` |
| Surcharge | 15% of tax — capped at this rate for listed-equity STCG/LTCG regardless of income slab (Finance Act 2022) | `RATES["surcharge_pct"]` |
| Cess | 4% of (tax + surcharge) — Health & Education Cess, applies at every income level | `RATES["cess_pct"]` |
| **STCG effective rate** | 20% × 1.15 × 1.04 ≈ **23.92%** | `STCG_RATE` |
| **LTCG effective rate** | 12.5% × 1.15 × 1.04 ≈ **14.95%** | `LTCG_RATE` |
| LTCG annual exemption | Rs 1,25,000 — tracked per financial year (see Rule 7) | `LTCG_EXEMPTION_INR` |
| LTCG holding threshold | 12 months | `LTCG_HOLDING_MONTHS` |
| STT on sell | 0.10% of sell value | `STT_SELL` |
| STT on buy | 0.10% of buy value (same rate as sell, real for delivery equity) | `STT_BUY` |
| Stamp duty on buy | 0.015% of buy value (buy-side only) | `STAMP_DUTY_BUY` |
| Brokerage + exchange charges | ~0.033% (both sides) | — |

**`STCG_RATE`/`LTCG_RATE` are the all-in effective rates actually used in
every CGT computation** — that's the rupee amount payable.
`STCG_STATUTORY_RATE`/`LTCG_STATUTORY_RATE` are the pre-surcharge figures,
kept only for display/decomposition.

### Derived per-rupee friction constants
```
TXN_COST_SELL = stt_sell + brokerage + exchange           ≈ 0.1335%
TXN_COST_BUY  = stt_buy + stamp_duty_buy + brokerage + exchange ≈ 0.1485%
```

---

## 3. Lot Classification (STCG vs LTCG)

### Rules
- `classify_term(acquisition_date, as_of)`: a lot is **LTCG** if held ≥ 12
  whole calendar months as of `as_of`, else **STCG**. Month counting is
  day-of-month aware (`months_between`).
- `ltcg_date(acquisition_date)`: the exact calendar date a lot crosses the
  12-month boundary and turns from STCG to LTCG (Feb 30-style overflow is
  clamped to the next valid date).

### Example
```
Acquired: 2025-03-15
LTCG date: 2026-03-15
as_of 2026-03-14 → STCG
as_of 2026-03-15 → LTCG
```

---

## 4. Per-Lot Tax Computation

### Rule (`compute_lot_tax`)
For a sale of `sell_shares` from one lot at `sell_price`:
```
gain = (sell_price - lot.cost_price) × sell_shares
term = classify_term(lot.acquisition_date, as_of)
rate = LTCG_RATE if term == "LTCG" else STCG_RATE
cgt  = gain × rate                      # negative for a loss lot
stt  = proceeds × STT_SELL
txn  = proceeds × TXN_COST_SELL
total_tax = cgt + txn
```
A loss lot produces **negative** `cgt` — this is intentional and is what
makes tax-loss harvesting attractive to the optimizer (Rule 8). STT/txn costs
still apply to a loss sale; only the CGT component can go negative.

---

## 5. Sale Attribution — Least-Tax-First (LTFO)

### Rule (`attribute_sale`)
When an order sells fewer shares than the full position, lots are consumed in
ascending order of **CGT per rupee of proceeds** (`_lot_tax_per_rupee`) —
loss lots and LTCG lots go first, STCG gain lots go last. This is **not**
FIFO/LIFO; it's "lowest tax exposure first."

### Output shape
Every SELL order carries a `tax` dict:
```json
{
  "stcg_gain": -289347.80,
  "ltcg_gain": 336384.00,
  "stcg_tax": -69221.73,
  "ltcg_tax": 50279.33,
  "stt": 38059.45,
  "txn_costs": 50790.33,
  "total_tax": 69907.38,
  "effective_rate_pct": 0.184,
  "lots_consumed": [
    {"lot_id": "...", "acquisition_date": "...", "shares": 25606, "term": "STCG", "gain": -289347.80},
    {"lot_id": "...", "acquisition_date": "...", "shares": 4672, "term": "LTCG", "gain": 336384.00}
  ],
  "tax_regime": "FY2025-26 synthetic PMS-style CGT + real STT/charges"
}
```

---

## 6. Buy-Side Transaction Costs

### Rule (`buy_txn_cost`)
There is no CGT on a buy (gains aren't realized until a later sale), but STT
and stamp duty are real friction regardless of side. Every BUY order carries
a `txn_cost` dict:
```json
{
  "stt": 177840.80,
  "stamp_duty": 26676.12,
  "brokerage_and_exchange": 59487.75,
  "total_cost": 264004.67,
  "rate_pct": 0.1485
}
```
Rolls up into `summary.est_total_buy_cost_cr` and
`tax_summary.buy_txn_cost_total`.

---

## 7. LTCG Exemption — Tracked Per Financial Year

### Purpose
The Rs 1.25 lakh LTCG exemption is an **annual** allowance, not a per-plan
one. A naive implementation that reapplies the full exemption to every
generated plan overstates relief when multiple plans are generated in the
same financial year.

### Rules
- **FY boundary:** Indian financial year runs Apr 1 → Mar 31
  (`planner._fy_start(as_of)`).
- **Already-used amount:** `planner._ltcg_exemption_used_this_fy(fund_id, as_of)`
  sums `tax_summary.ltcg_exemption_used_inr` from this fund's
  **approved + sent** plans (see Rule 9 for that bar) created on or after the
  current FY's Apr 1.
- **Remaining exemption:** `max(LTCG_EXEMPTION_INR - already_used, 0)`,
  applied against this plan's net LTCG gain. Whatever isn't used carries
  forward within the same FY; nothing carries across FY boundaries.

### Output fields (`tax_summary`)
```json
{
  "ltcg_exemption_relief": 18687.50,
  "ltcg_exemption_used_inr": 125000.00,
  "ltcg_exemption_remaining_inr": 0.00
}
```

### Example
```
Plan 1 (first of FY 2026-27): net LTCG gain 200,000 → full Rs 1.25L exemption applied
  ltcg_exemption_used_inr = 125,000 · ltcg_exemption_remaining_inr = 0

Plan 2 (same FY, after Plan 1 approved + sent): net LTCG gain 80,000
  → Rs 0 exemption remaining → full gain taxed at LTCG_RATE
```

---

## 8. Lot Consumption — No Double-Counting Across Plans

### Purpose
Tax lots are reattached fresh from the synthetic universe on every plan
generation. Without cross-plan awareness, a lot an earlier **approved + sent**
plan already sold would still show up as available and could be "sold" again
by a later plan — understating that later plan's real tax.

### Rules
- **Commitment bar:** Only plans with status containing "approved" or "sent
  to trading" **and** at least one row in `sent_emails` count — the same bar
  `_augment_pending_trades_from_approved_plans` already uses for cash/shares
  (`planner._approved_sent_plans`).
- **Consumption tracking:** `planner._consumed_tax_lots_by_ticker(fund_id)`
  sums `lots_consumed` (lot_id → shares) from those plans' SELL orders' `tax`
  breakdowns.
- **Trim before attribution:** `tax_lots.apply_consumed_lots(holding,
  consumed_by_lot_id, as_of)` reduces each lot's quantity by what was already
  sold (dropping lots that reach zero) and recomputes the holding's derived
  tax fields (`avg_cost`, `stcg_shares`, `ltcg_shares`,
  `effective_tax_rate_pct`) from the trimmed lot list.
- **Index rebuild:** `ds["holdings_by_ticker"]` is rebuilt from the trimmed
  holdings so every lookup by ticker (order attribution, policy checks) sees
  the adjusted lots too — not just `ds["holdings"]` iteration.
- **Cache safety:** Holdings are shallow-copied before trimming (same
  shared-cache-mutation hazard already fixed for `pending_trades`).

### Verified example
```
AXISBANK lot INE238A01034-L1, original quantity: 30,350
Plan 1 (approved + sent): sells 4,672 shares from this lot
Plan 2 (same fund, later): lot now shows 25,678 remaining
  → Plan 2 sells exactly the remaining 25,678 → lot fully consumed, no overlap
```

---

## 9. Optimizer Integration

**Tax is baked directly into the convex objective itself — it is not a
post-solve ranking step.** Both sell-side optimizers solve a single cvxpy
problem where the tax/cost terms are coefficients inside the same
`cp.Minimize`/`cp.Maximize` the solver optimizes, so the chosen trades are
already tax-aware by construction, not re-ordered afterward.

### `optimize_sell` ([optimizer.py:190-208](../backend/app/optimizer.py))
```python
cost = ret * horizon_scale + tax + txn
cp.Problem(cp.Minimize(coeff @ val), cons)   # coeff = cost
```
`tax` here is each candidate's `tax_rate` (the holding's
`effective_tax_rate_pct`, negative for a net-loss position) — a linear
coefficient the LP minimizes alongside forecast return given up and
transaction cost. Loss positions are cheap to sell in this objective, so the
solver naturally prefers tax-loss harvesting over realizing gains on a
same-forecast-return winner.

**Horizon scaling:** expected return is scaled by `horizon_days / 21` before
comparing against tax, because tax is paid once but a predicted loss repeats
every period — a persistently losing stock is sold even if its exit tax is
high.

**Second, tax-blind solve for reporting only:** `optimize_sell` also runs a
*separate* solve with `coeff = ret * horizon_scale` (tax/txn terms omitted) to
get `naive_tax_cr`, purely to compute `tax_saved_vs_naive_cr` (line 259) as a
"what would a tax-blind plan have cost" comparison. This second solve's
result is never returned as the plan — the actual `sells` always come from
the tax-aware solve above.

### `optimize_rebalance` ([optimizer.py:287-300](../backend/app/optimizer.py))
```python
exit_cost = clip(effective_tax_rate_pct/100 + txn_cost_rate_pct/100, 0, None)
tax_penalty = exit_cost @ cp.pos(w_cur - w)
cp.Problem(cp.Maximize(ret @ w - tax_penalty), cons)
```
The tax penalty is a convex term subtracted from expected return inside the
same `Maximize`, clipped at 0 on the sell side only so it never rewards
realizing a loss twice (that reward already lives in `optimize_sell`'s
negative tax rate) — so rebalances don't needlessly churn high-tax winners.

### Rules path (`_funding_sells`)
Ties on portfolio weight are broken by preferring the lower-tax exit. This
path has no convex solver — it's a direct comparison, used only when the
optimizer path isn't applicable.

### Post-trade: exact attribution, not re-optimization
Once orders are chosen (by either path above), `planner.py` attaches an
**exact** per-order tax breakdown via `tax_lots.sale_tax_breakdown()` —
lot-level least-tax-first attribution (Rule 5), which is more precise than
the `effective_tax_rate_pct` estimate the optimizer used *during* solving
(that estimate is a position-wide blended average; the real attribution
walks individual lots). `_tax_context()` then aggregates these into
`tax_summary` and feeds `policy.evaluate()` for the TAX-* checks (Rule 10).
**This step is purely computational/reporting — it never changes which
trades were chosen**, only how precisely their tax is reported.

### Worked example — tax changing which stocks get sold
A live redemption plan (raise ₹30cr from HDFC Flexi Cap) demonstrates all of
the above together:
- `optimization.tax_saved_vs_naive_cr: 0.33` — the tax-aware solve saved
  ₹33 lakh versus a tax-blind one by preferring loss lots.
- `tax_summary.held_due_to_tax` listed **9 holdings** with negative forecast
  returns (ICICIBANK, HYUNDAI, TATASTEEL, BEL, ANTHEM, KPIL, APARINDS,
  BIOCON, ATHERENERG) that were **not** sold, because each one's exit cost
  (2–9.7%) exceeded its expected loss over the horizon — tax overrode "this
  stock is forecast to lose money, sell it."
- The resulting `TAX-HOLD` policy check fired once per holding above, e.g.
  *"BEL has a negative forecast return (-0.31%) but was kept because its
  exit cost (2.953%) exceeds the expected loss over the horizon. STCG lots
  turn LTCG on 2026-11-01"* — naming the exact date the trade gets cheaper.

---

## 10. Policy Guardrails

`policy.py` adds the following checks (WARN/ESCALATE only — never a hard
BLOCK; the human still decides):

| Check | Condition |
|---|---|
| **TAX-DRAG** | WARN above 60 bps of sell proceeds, ESCALATE above 150 bps |
| **TAX-STCG-SHARE** | WARN when >50% of sell value comes from short-term lots |
| **TAX-HOLD** | WARN when a stock with a negative forecast return was kept only because its exit cost exceeds the expected loss over the horizon, including the date its remaining STCG lots turn LTCG |

---

## 11. Synthetic Tax Lots

### Purpose
Fund disclosures give quantity / market value / %NAV only — never purchase
history — and no external source exists for a fund's private lots. Lots are
synthesized but anchored to reality.

### Rules
- **Cost prices are real:** each lot's cost price is the stock's actual
  `monthly_close` on its synthetic acquisition date
  (`data/processed/final/stock_macro_monthly_target.csv`), so unrealized
  gain/loss reflects genuine price history.
- **Lot count:** 2–5 lots per holding, deterministic per ISIN (seeded
  `random.Random(sha256(isin))`), reproducible across restarts.
- **Guaranteed term mix:** at least one lot placed 13–36 months back
  (guaranteed LTCG) and, where the position is large enough, one placed
  1–11 months back (guaranteed STCG).
- **Loss candidates:** ~18% of holdings get a lot deliberately placed at the
  highest real close in the trailing 36 months, so genuine loss lots exist
  for tax-loss-harvesting demos.
- **Persistence:** `python -m app.tax_lots` writes the generated lots to
  [data/processed/tax/tax_lots.csv](../data/processed/tax/tax_lots.csv);
  `attach_tax_data()` prefers this persisted file and falls back to the
  identical deterministic generator for any holding missing from it.

### Derived holding fields
`tax_lots[]`, `avg_cost`, `unrealized_gain_pct`, `stcg_shares`,
`ltcg_shares`, `effective_tax_rate_pct`, `txn_cost_rate_pct`, `tax_source`.

---

## 12. Plan-Level Output Fields

### `summary`
```json
{
  "est_total_tax": 69907.38,
  "est_total_tax_cr": 0.0070,
  "tax_drag_bps": 23.4,
  "stcg_share_pct": 84.6,
  "est_total_buy_cost": 264004.67,
  "est_total_buy_cost_cr": 0.0264
}
```

### `tax_summary`
```json
{
  "est_total_tax": 69907.38,
  "ltcg_exemption_relief": 18687.50,
  "ltcg_exemption_used_inr": 125000.00,
  "ltcg_exemption_remaining_inr": 0.00,
  "sell_value": 299000000,
  "tax_drag_bps": 23.4,
  "stcg_share_pct": 84.6,
  "held_due_to_tax": [ { "ticker": "...", "expected_return_pct": -1.2, "exit_cost_pct": 3.4, "ltcg_maturity": "2027-01-15" } ],
  "buy_txn_cost_total": 264004.67,
  "rates": { "...": "full RATES dict, incl. effective rate percentages" },
  "note": "Synthetic PMS-style capital-gains layer + real STT/charges. Actual Indian mutual funds are CGT-exempt at fund level (Section 10(23D)); see docs/taxation-model.md."
}
```

### `optimization.tax_saved_vs_naive_cr`
Compares the tax-aware solve against a tax-blind one for storytelling.

---

## 13. UI Visibility — What's Actually Shown to the User

Verified against `frontend/src/components/TradePlanner.jsx`:

| Field | Shown to user? | Where |
|---|---|---|
| `optimization.tax_saved_vs_naive_cr` ("X tax saved vs. a tax-blind plan") | **Yes** | Inside the "Optimizer:" info alert, only when `> 0` |
| `summary.est_total_tax` / `tax_drag_bps` / `stcg_share_pct` | **Yes** | A KPI stat tile "Est. Exit Tax", colored red when drag exceeds 60 bps |
| `tax_summary.held_due_to_tax` (stocks **not** sold because exit tax outweighed the expected loss) | **Yes** | "Held Due to Tax" table (Security / Return / Exit Cost / LTCG Turns) in the "Tax Impact" column |
| `policy_checks` — `TAX-HOLD` / `TAX-DRAG` / `TAX-STCG-SHARE` | **Yes** | Same "Tax Impact" column, filtered to `code.startsWith('TAX-')`, each with a PASS/WARN/ESCALATE chip |

### Where it lives
The "Compliance Checks & Risk Flags" panel was renamed **"Compliance, Tax &
Risk"** and extended to three columns (`TradePlanner.jsx`): Compliance |
**Tax Impact** (new) | Execution Risk. The Tax Impact column scrolls
internally at 220px (matching the Execution Risk register's own height cap)
so a plan with many `TAX-HOLD` entries doesn't blow out the page. The
existing Execution Risk register also picked up a friendly **"Tax impact"**
group label (previously the raw category string `taxation`) for the same
`TAX-HOLD`/`TAX-DRAG`/`TAX-STCG-SHARE` entries it already received via
`plan.risk_flags` — the two panels are complementary, not duplicates: the
register shows only non-PASS findings grouped by category, the dedicated
column shows the full check set (including PASS) plus the structured
per-stock table.

### Worked examples — reproducing "a few stocks held due to tax" per fund
`held_due_to_tax` count varies a lot by fund and redemption size (scanned via
`planner.generate_plan()` directly, action=`redemption`):

| Fund | Redemption Amount | Stocks held due to tax |
|---|---|---|
| Kotak Large & Mid Cap Fund | ₹20 Cr | **4** |
| HDFC Flexi Cap Fund | ₹50 Cr | **5** |
| ICICI Prudential Large Cap Fund | ₹50 Cr | **6** |
| SBI Nifty 50 ETF | ₹10–50 Cr | flat **7** (doesn't change with amount) |
| HDFC Retirement Fund – Equity Plan | ₹10–50 Cr | **0** (never shows any at these amounts) |

**Recommended reproduction (clean, small example):** select **Kotak Large &
Mid Cap Fund** in the fund dropdown → **Redemption** → amount **₹20 Cr** →
**Generate Plan** → scroll to **Compliance, Tax & Risk → Tax Impact → Held
Due to Tax**.

---

## 14. Known Limitations & Future Enhancements

### Current Limitations
1. **No wash-sale rule** — the app doesn't model reinvestment/repurchase
   restrictions (India doesn't have a generic wash-sale rule, but bonus-
   stripping restrictions exist and aren't modeled).
2. **No loss carry-forward across financial years** — only intra-sale lot
   netting and the same-FY exemption tracking (Rule 7).
3. **Flat assumed surcharge** — 15% is the statutory cap for listed-equity
   capital gains regardless of income slab, but a real investor's situation
   could differ if law changes this cap.
4. **Single approved-plan ledger per fund** — cross-plan state (Rules 7 & 8)
   is scoped per `fund_id`; it doesn't reason about an investor holding the
   same security across multiple funds.

### Possible Enhancements
- Model loss carry-forward (short-term losses offset both STCG/LTCG;
  long-term losses offset LTCG only; 8-year carry window under Indian law).
- Make the assumed surcharge rate configurable per investor profile instead
  of a single flat default.
- Persist lot consumption transactionally at execution time instead of
  recomputing it from approved-plan history on every request.

---

## 15. Testing & Validation

### Unit Tests
`backend/tests/test_tax.py` — 14 tax-specific tests covering:
- Term classification boundary (exactly 12 months → LTCG)
- LTCG-date computation
- Loss lots producing negative CGT with positive STT/txn costs
- STCG/LTCG rate application
- Least-tax-first lot attribution
- Lot generation determinism and share-sum invariants
- Optimizer tax-aware selling (prefers low-tax exit, persistent-loser sale
  despite high exit tax) and tax-aware rebalancing
- Policy tax checks (TAX-DRAG, TAX-STCG-SHARE, TAX-HOLD)

Run: `python -m unittest tests.test_tax tests.test_policy tests.test_forecast`
— 17 tests pass (no regressions as of this document's version).

### Manual Verification
- SBI Nifty 50 ETF AUM sanity-checked after the xlsx-parser fix (%NAV sums to
  ~99.97%, AUM ~₹2.16 lakh Cr).
- Approve → re-plan cycle confirmed no lot is ever oversold across two
  separately generated plans (Rule 8 example above).
- LTCG exemption confirmed to zero out on a second same-FY plan after a first
  plan consumed it in full (Rule 7 example above).

### Independent Recompute — Per-Order Tax Breakdown
To validate the displayed tax figures are actually correct (not just
internally self-consistent), one order's `tax` breakdown was recomputed from
scratch using only raw primitives — lot `cost_price`/`quantity` and the
published rate constants — **without calling `attribute_sale()` or any
function under test**, then compared to the live plan output.

**Example: AXISBANK, redemption plan, 30,278 shares sold, 2 lots spanning
both terms**

| Field | App output | Independent recompute |
|---|---|---|
| stcg_gain | -289,347.80 | -289,347.80 |
| ltcg_gain | 336,384.00 | 336,384.00 |
| stcg_tax | -69,211.99 | -69,211.99 |
| ltcg_tax | 50,289.41 | 50,289.41 |
| stt | 38,059.45 | 38,059.45 |
| txn_costs | 50,790.33 | 50,790.33 |
| total_tax | 31,867.74 | 31,867.74 |

Exact match: `(real_price − lot.cost_price) × shares_from_lot × rate`,
summed per lot. One subtlety this surfaced: tax uses the holding's **real
market price**, not necessarily the order's displayed price (which can be a
synthetic-universe forecast price for some tickers) — see the note in Rule 4.

### Independent Recompute — Plan-Level Rollup
Summing `total_tax` across all 28 SELL orders in the same plan and netting
the LTCG exemption reproduced `tax_summary.est_total_tax` exactly
(`-3,299,206.15` both ways), and `sell_value`-weighted `tax_drag_bps`
(`-100.6` both ways) matched a manual `tax / sell_value × 10,000` recompute.
Confirms the per-order → plan-level aggregation has no silent drift.

---

## 16. Maintenance & Troubleshooting

### Regenerating synthetic tax lots
```bash
cd backend
python -m app.tax_lots
```

### Rebuilding the database after a rates/schema change
```bash
cd backend
python scripts/init_db.py --reset
```
`--reset` drops and recreates all tables including `tax_rules` and
`tax_lots`, re-seeding from `data/processed/tax/tax_rates.json` and the
persisted lots CSV. Safe only when no plans need to be preserved (check
`SELECT COUNT(*) FROM plans` first).

### Common Issues

**Tax figures changed after a rate edit:**
- Check `data/processed/tax/tax_rates.json` first — it's the fallback source.
- Check the `tax_rules` DB table — it's the source of truth once
  `init_db.py` has run; a stale DB row overrides a JSON edit until reset.

**A lot appears "sold twice":**
- Confirm both plans are actually in the same fund (`_consumed_tax_lots_by_ticker`
  is scoped per `fund_id`).
- Confirm the earlier plan's status contains "approved"/"sent to trading"
  **and** has a row in `sent_emails` — plans still "Pending PIC Review" don't
  count and won't trim lots for later plans.

---

## References

- **Core rules:** `backend/app/tax_rules.py` — rates, lot classification,
  per-lot tax, sale attribution, buy-side cost
- **Synthetic lots:** `backend/app/tax_lots.py` — generation, persistence,
  cross-plan consumption trimming
- **Integration:** `backend/app/planner.py` — tax context, cross-plan state,
  buy/sell order attachment
- **Optimizer:** `backend/app/optimizer.py` — tax-aware sell/rebalance
  objectives
- **Policy:** `backend/app/policy.py` — TAX-DRAG / TAX-STCG-SHARE / TAX-HOLD
- **Config:** `data/processed/tax/tax_rates.json`,
  `data/processed/tax/tax_lots.csv`
- **DB:** `backend/scripts/init_db.py` — `tax_rules` / `tax_lots` schema and
  seeding
- **Tests:** `backend/tests/test_tax.py`
- **Narrative companion doc:** [taxation-model.md](taxation-model.md)

---

## Document Revisions

| Version | Date       | Author | Changes                                                        |
|---------|------------|--------|-----------------------------------------------------------------|
| 1.0     | 2026-10-02 | Claude | Initial comprehensive documentation of all taxation rules currently implemented (statutory + effective rates, buy-side costs, FY-aware exemption, cross-plan lot consumption, optimizer/policy integration) |
| 1.1     | 2026-10-02 | Claude | Added independent validation of per-order and plan-level tax math (Section 15), clarified exactly where tax enters the convex optimizer vs. the post-trade exact-attribution step (Section 9), and added a UI-visibility audit of which tax fields actually reach the user (Section 13) |
| 1.2     | 2026-10-02 | Claude | Wired `held_due_to_tax` and the `TAX-*` entries of `policy_checks` into the Trade Planner UI (new "Tax Impact" column); updated Section 13 to reflect this (no longer a gap) and added a cross-fund worked-examples table for reproducing a small "held due to tax" count |
