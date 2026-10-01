# Final Plan Generation Rules

This document describes every rule applied while generating a trade plan in the
PIC platform. Rules fall into **two distinct layers**:

- **Layer A — constraints baked into the convex optimization.** Enforced
  mathematically by the CVXPY solver while the trades are being constructed. The
  optimizer cannot propose a solution that violates them (subject to the
  relaxation ladder below).
- **Layer B — policy / compliance rules checked after trades are proposed.**
  Re-checked independently against the **post-trade** book. These produce
  `PASS` / `WARN` / `BLOCK` / `ESCALATE` results.

> **A suggestion from the optimizer is not approval.** Every plan runs the full
> post-trade policy gauntlet and comes back as `Pending PIC Review`. A blocked
> plan is returned for review, not silently discarded.

Source code: [`optimizer.py`](../backend/app/optimizer.py),
[`planner.py`](../backend/app/planner.py),
[`policy.py`](../backend/app/policy.py).

---

## Layer A — Rules enforced *inside* the convex optimization

Encoded as hard constraints in the CVXPY programs. Money terms are scaled to
crore before solving for numerical stability.

### A.1 Buy / Contribution — `optimize_buy`

**Objective:** maximize forecast expected return of deployed capital
(`Maximize(ret @ buy)`).

| Rule | Constraint |
|---|---|
| Full deployment | `sum(buy) == amount` — the whole ticket must be allocated |
| Long-only | `buy >= 0` — no negative / short buys |
| Per-issuer cap | `cur + buy <= issuer_cap` — existing + proposed stays within the fund's single-issuer limit |
| Per-sector cap | `sector_current + sum(buy_in_sector) <= sector_cap` |
| Per-name diversification | `buy <= 34% of ticket` — no single name takes most of the buy |

- Caps are measured against **post-trade AUM** for a contribution
  (pre-trade AUM + deployed cash); against current AUM for other buys.
- **Relaxation ladder when infeasible:** drop the 34% per-name cap → then drop
  the sector cap (issuer cap always kept) → else fall back to the rule-based
  path. Any residual sector breach is surfaced by the policy layer afterward.

### A.2 Sell / Redemption — `optimize_sell`

**Objective:** raise the target while giving up the least — minimizes
`horizon-scaled forecast return + exit tax + transaction cost` per rupee sold
(tax-aware).

| Rule | Constraint |
|---|---|
| Lock-in respect | `val <= sellable_value` — only *sellable* shares (locked / pledged excluded) |
| Cannot over-raise | target capped at total sellable value |
| Per-name cap | `val <= 34% of target` — spreads the raise to limit market impact |
| Tax-awareness | prefers LTCG / loss lots over short-term winners; loss lots carry a negative tax rate |

- The forecast return is scaled over the execution horizon (~21 trading days /
  month) because tax is a one-time cost while a predicted loss repeats.
- **Relaxation:** drop the 34% per-name cap if too few names have capacity;
  available-share limits always remain.

### A.3 Rebalance — `optimize_rebalance`

**Objective:** maximize expected return net of exit tax.

| Rule | Constraint |
|---|---|
| Cash-neutral | `sum(w) == invested` — stays as invested as it is now |
| Long-only | `w >= 0` |
| Per-issuer cap | `w <= issuer_cap` (generic 10%, **not** fund-specific) |
| Turnover budget | `norm1(w - w_cur) <= 15%` — limits total churn |
| Tax penalty | realized-gain tax penalizes churning high-tax (short-term winner) positions |

After optimization, planner code ignores rebalance changes below ₹0.25 Cr and
caps each sale at shares available to sell.

---

## Layer B — Rules checked *after* trades are proposed

Run in [`policy.py`](../backend/app/policy.py) `evaluate()`, re-checked against
the **post-trade** book (projected exposures divide by post-trade AUM).

### B.1 Concentration checks (`_concentration_checks`)

| Check | Code | Rule |
|---|---|---|
| Single issuer | `MANDATE-ISSUER` | Projected issuer weight vs fund single-issuer limit |
| Sector | `MANDATE-SECTOR` | Projected sector weight vs sector soft limit |
| Group | `MANDATE-GROUP` | Projected group weight vs group limit |
| UCITS 5/40 | `UCITS-5-40` | Positions each above 5% must aggregate under 40% |
| Country | `COUNTRY-LIMIT` | Home 100% / foreign 35% / emerging 20% |

**Status logic:** `> limit` → `BLOCK`; `>= 90% of limit` → `WARN`; otherwise
`PASS`. A pre-existing breach worsened by no more than 0.01 pp → `WARN` rather
than `BLOCK`, so an unrelated trade is not blocked by an inherited breach.

### B.2 Per-order & plan checks (`_order_checks`)

| Check | Code | Result |
|---|---|---|
| Restricted / pledged security | `RESTRICTED-SECURITY` | `BLOCK` |
| Watchlist security | `WATCHLIST-SECURITY` | `ESCALATE` |
| Sell exceeds available-after-pending | `RESTRICTED-SELL` | `BLOCK` |
| Sale breaches minimum holding | `MIN-HOLDING` | `BLOCK` |
| Lock-in (within sellable) | `LOCK-IN` | `PASS` (note only) |
| ESG exclusion on new buy (e.g. ITC / tobacco) | `ESG-EXCLUSION` | `BLOCK` the buy |
| Thermal-power generation > 20% on buy | `ESG-THERMAL-POWER` | `WARN` |
| Stale price | `PRICE-FRESHNESS` | `BLOCK` |
| Liquidity / ADV (daily participation over horizon) | `LIQUIDITY-ADV` | > 5%/day `WARN`; > 75%/day `ESCALATE`; missing ADV `ESCALATE` |
| Bid-ask spread | `LIQUIDITY-SPREAD` | > 0.5% `WARN`; > 1% `BLOCK` |
| Foreign-currency exposure | `FX-EXPOSURE` | > 10% `WARN`; > 15% `BLOCK` |
| Corporate-action window | `CORP-ACTION-WINDOW` | within 1d dividend / 2d other → `WARN` |
| Cash deployment | `CASH-DEPLOYMENT` | net buys must fit within 95% operational cash + 100% of the fresh subscription, else `BLOCK` |
| Order count | `PLAN-ORDER-COUNT` | > 50 `WARN`; > 100 `ESCALATE` |
| Execution horizon | `PLAN-HORIZON` | > 20 days `ESCALATE` |

Liquidity is treated as a **schedulable** constraint: a parent order too big for
a single day is worked across the horizon (`ESCALATE` for review) rather than
hard-blocked, so large flows stay executable.

### B.3 Tax-awareness guardrails (`_tax_checks`) — `WARN` / `ESCALATE` only

These never block; the human decides.

| Check | Code | Result |
|---|---|---|
| Tax drag (bps of sell proceeds) | `TAX-DRAG` | > 60 bps `WARN`; > 150 bps `ESCALATE` |
| STCG share of sell value | `TAX-STCG-SHARE` | > 50% `WARN` |
| Loser kept because exit cost exceeds expected loss | `TAX-HOLD` | `WARN` |

### B.4 Legacy compliance summary (`planner._compliance_checks`)

A second, older concentration summary runs in
[`planner.py`](../backend/app/planner.py): `SEBI-10PCT` (single issuer),
`SECT-35PCT` (sector), `GRP-20PCT` (group). Status is `FAIL` / `WARN` / `PASS`,
and a `FAIL` here also forces `execution_allowed = false`. Prefer the returned
`policy_status` / `execution_allowed` fields for the clearest overall result.

---

## How the checks decide the final plan result

Policy combines all check results in this order:

1. Any `BLOCK` → overall status `BLOCK`, `execution_allowed = false`.
2. Else any `ESCALATE` → status `ESCALATE`, `execution_allowed = false`.
3. Else any `WARN` → status `WARN`; execution allowed, but review advised.
4. Else `PASS`; execution allowed.

A `FAIL` in the legacy planner summary also sets `execution_allowed = false`.

---

## Why the optimizer and policy can disagree

- The optimizer **constructs** a proposed allocation; it is not the final
  approval authority. For buys it can relax its sector cap after an infeasible
  solve; post-order policy then checks the configured sector limit
  independently.
- Held securities are added to optimizer buy candidates **before** the exclusion
  filter used for new universe names. A restricted / pledged / ESG-excluded
  existing holding can therefore be proposed as a new buy; the post-order policy
  check blocks it.
- Optimized rebalance uses a generic 10% company limit, which can differ from
  the fund-specific limit used by buy optimization and policy.
- Active data labels each holding's business group with its own ticker, so the
  configured group limit does not currently combine affiliated companies.
- Expected returns are placeholder illustrative values in
  [`forecast.py`](../backend/app/forecast.py), not live TFT predictions. The
  optimizer's ranking is therefore a demo input; the rules above are real.

> The numeric thresholds in this document are current demo / POC settings from
> code (overlaid from the database where present). They are **not** confirmed
> legal or fund mandates.

---

## Code locations

| Responsibility | File and function |
|---|---|
| Optimizer goals, constraints, retry behavior | `backend/app/optimizer.py`: `optimize_buy`, `optimize_sell`, `optimize_rebalance` |
| Allocation method, fallback to rules, order forming, final plan | `backend/app/planner.py`: `_orders_by_optimizer`, `_orders_by_rules`, `generate_plan` |
| Post-trade concentration, eligibility, execution, cash, tax, plan limits | `backend/app/policy.py`: `_concentration_checks`, `_order_checks`, `_tax_checks`, `evaluate` |
| Active fund limits and holdings | `backend/app/data_v2.py`: `FUND_COMPLIANCE_LIMITS` |
| Expected returns | `backend/app/forecast.py`: `predict_returns` (placeholder data) |
