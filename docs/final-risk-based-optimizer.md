# Final: Risk-Based Optimizer — How Risk/Return Is Wired Into Convex Optimization

This document explains how the risk/return metrics described in
[nav-risk-return-metrics.md](nav-risk-return-metrics.md) and
[data-v2-real-vs-curated.md](data-v2-real-vs-curated.md) actually get **used** —
end to end, from the database up through the UI slider and back down into the
CVXPY convex program that generates a trade plan.

---

## 1. Two layers, two different jobs

There are two separate risk/return computations in this system. They look
similar but serve different purposes and run at different times:

| Layer | Where | When it runs | What it's for |
|---|---|---|---|
| **Batch summary metrics** | [compute_risk_return_metrics.py](../backend/scripts/compute_risk_return_metrics.py) → `stock_risk_return_metrics` / `fund_risk_return_metrics` tables | Offline, as part of the data pipeline (before `init_db.py` seeds the DB) | The risk/return **graph** in the UI, and the fund's strategy **mandate band** (default slider range, computed from the fund's own rolling history — see §3) |
| **Runtime covariance model** | [risk_model.py](../backend/app/risk_model.py) | Live, per trade-plan request | The actual **Σ (covariance matrix)** the optimizer constrains against |

The batch layer gives you a point-in-time *picture* (one row per stock, one row
per fund) — cheap to query, good for charts. It does **not** store a
covariance matrix (that would be an N×N table per fund, impractical to keep
fresh). The runtime layer builds the covariance matrix **on demand**, scoped
to exactly the tickers a given plan touches, directly from
`stock_prices` history.

---

## 2. End-to-end data flow

```
stock_prices (DB, monthly OHLCV)
        │
        ├─▶ compute_risk_return_metrics.py (offline)
        │         │
        │         ▼
        │   stock_risk_return_metrics / fund_risk_return_metrics (DB)
        │         │
        │         ▼
        │   GET /api/risk-return?fund_id=...  (main.py)
        │         │
        │         ▼
        │   RiskReturnPanel.jsx — scatter chart + mandate band + slider
        │         │
        │         ▼
        │   user drags the volatility slider → target_volatility
        │         │
        │         ▼
        │   POST /api/trade-plan  { ..., target_volatility: 0.14 }
        │         │
        └─────────┼───────────────────────────────────────────────┐
                  ▼                                                │
         planner._build_risk_context(ds, target_volatility)        │
                  │                                                │
                  ├─ resolves sigma_max (explicit > mandate band)   │
                  ├─ risk_model.build_covariance(holdings' tickers) │ (reads
                  ├─ risk_model.extend_with_diagonal_fallback(...)  │  stock_prices
                  ▼                                                │  live)
         risk = {tickers, cov_monthly, target_volatility, ...}       │
                  │                                                │
                  ▼                                                │
     optimizer.optimize_buy / optimize_sell / optimize_rebalance ◀──┘
     (adds  w^T · Σ · w  <=  sigma_max² / 12  as a CVXPY constraint)
                  │
                  ▼
         plan.optimization.risk_target_achieved_annual / target_volatility
         plan.risk_return  (post-trade estimate, for display)
```

---

## 3. Resolving the volatility target

`planner._build_risk_context()` selects the annualized volatility target in this
order:

1. **Explicit `target_volatility`** on the intent (`IntentRequest.target_volatility`
   in [schemas.py](../backend/app/schemas.py)) — what the PIC associate set on
   the slider.
2. Else, the fund's **`strategy_volatility_high`** — the mandate band's upper
   edge, seeded into `fund_risk_return_metrics`. This band is *computed*, not
   hand-picked: the 20th/80th percentile of annualized return/volatility
   across rolling 3-year windows of the fund's own synthetic history (see
   [data-v2-real-vs-curated.md](data-v2-real-vs-curated.md)), with a
   risk_grade-sized fallback for a fund with too little history for rolling
   windows.
3. Else — no target. The optimizer runs exactly as it did before this
   feature existed.

This mirrors the UI: the slider initializes at the fund's mandate upper edge,
and the PIC associate can move the target from 0% to 100%. The optimizer first
finds a feasible return-oriented allocation, then refines it toward the
requested historical-volatility target. If trading constraints make the target
unreachable, the plan reports achieved volatility and the target gap.

---

## 4. Building the covariance matrix

`risk_model.build_covariance(tickers, isin_by_ticker)`:

1. Pulls each ticker's full monthly price history (`db.get_stock_price_levels`)
   and converts it to period returns (`level_t / level_{t-1} - 1`).
2. Finds the common (inner-join) set of months across all tickers, dropping
   whichever ticker has the least history until the rest clear
   `MIN_OBSERVATIONS = 12` months of overlap.
3. Computes the sample covariance (`np.cov`) over that common window.
4. Clips negative eigenvalues (`_nearest_psd`) so CVXPY's `quad_form` accepts
   the matrix — a short/ragged sample covariance can be slightly indefinite.

Any ticker that doesn't make the cut (too little history, or none at all —
e.g. a recently added holding) is **not excluded from the risk picture**.
`risk_model.extend_with_diagonal_fallback()` appends it to the matrix as an
uncorrelated, diagonal-only entry using its own `annualized_volatility` from
`stock_risk_return_metrics` (or the fund's own volatility as a last-resort
default). Without this, such a ticker would simply vanish from the
constraint — understating risk for any book that holds it.

---

## 5. Target tracking

For a weight vector `w` (fraction of AUM per ticker, in the same order as the
covariance matrix) and monthly covariance `Σ`:

```
w^T · Σ · w  <=  target_volatility² / 12
```

Dividing by 12 converts the annualized target into a monthly-variance bound,
consistent with the monthly covariance (annualizing variance multiplies by the
number of periods/year; de-annualizing divides by it). The initial convex solve
uses this as a bound. A follow-up constrained SLSQP fit minimizes the distance
between achieved and requested annualized volatility, preserving each action's
trading constraints. That second stage is shared across buy, sell, and rebalance.

**How `w` is built differs by action**, because each optimizer function has a
different decision variable:

| Function | Decision variable | Post-trade weight per ticker |
|---|---|---|
| `optimize_buy` | `buy[i]` = crore deployed to candidate *i* | `(current_value + buy[i]·₹1cr) / post_trade_AUM` for candidates; fixed `current_value / post_trade_AUM` for every other held ticker |
| `optimize_sell` | `val[i]` = crore sold from candidate *i* | `(current_value − val[i]·₹1cr) / AUM` for candidates; fixed otherwise |
| `optimize_rebalance` | `w[i]` = target weight of holding *i* (already a fraction of AUM) | `w[i]` directly — no conversion needed, the variable *is* the weight |

Tickers outside the acting function's candidate set keep their **current**
weight as a constant in the expression — they're not being traded, but they
still count toward portfolio risk.

---

## 6. Feasibility and fallback

The initial convex risk bound can be relaxed to find a feasible starting
allocation. The target-fit stage then aims for the closest attainable
volatility without relaxing the final allocation constraints. Policy checks
still run on the resulting plan; an unreachable target is reported as a gap
rather than an exact match.

---

## 7. What ends up in the plan response

Every generated plan (`planner.iter_plan_steps` / `generate_plan`) carries two
risk-related blocks:

- **`plan.optimization`** — the solver's own metadata, including
  `risk_target_achieved_annual` and `target_volatility`. The legacy
  `risk_constrained` flag (also exposed as `initial_risk_bound_applied`) notes
  whether the initial convex bound was retained while finding a starting
  allocation; target fitting runs afterward either way.
- **`plan.risk_return`** — comparable pre/post historical annualized return
  and volatility (`planner._estimate_post_trade_risk_return`), computed from
  stock history and the final order list (whether optimizer, rules, or manual
  produced it). Forecast return estimates are not used in these metrics.
  Contribution/redemption cash flows adjust post-trade AUM; cash is treated as
  zero-return and zero-volatility. Metric and covariance coverage are included
  so missing historical data is visible.

---

## 8. Frontend wiring

- [RiskReturnPanel.jsx](../frontend/src/components/RiskReturnPanel.jsx) fetches
  `GET /api/risk-return?fund_id=...`, renders the stock-level scatter, the
  fund's current point, the shaded mandate band, and the volatility slider
  (capped at 100%, highlighted between the band's min/max, with an inline
  warning if dragged outside that range).
- [TradePlanner.jsx](../frontend/src/components/TradePlanner.jsx) holds the
  slider's value as `targetVolatility` state, sends it as
  `target_volatility` on `POST /api/trade-plan`, and displays
  `plan.risk_return` next to the optimizer's own summary once a plan comes
  back.

---

## 9. Known simplifications

- **Monthly, not daily, data** — covariance and volatility are computed on
  monthly returns; annualization assumes 12 independent periods/year.
- **Risk-free rate is an assumption** — `compute_risk_return_metrics.py` uses a
  fixed 6.5% risk-free rate, not an ingested one. The mandate band itself is
  computed from the fund's own rolling history (not hand-picked), but that
  history is still the same long, volatile 2010–2026 backtest everything else
  in this doc is built on.
- **Historical portfolio returns are weighted stock-level annualized returns**
  rather than a full historical portfolio backtest. Holdings with no stock
  return metric contribute zero return; the response reports metric coverage.
- **No forward-looking risk model** — the covariance is purely historical
  (sample covariance over available monthly history), with no shrinkage,
  factor model, or regime-awareness beyond the diagonal fallback in §4.
