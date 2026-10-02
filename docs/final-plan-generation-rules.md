# Final Plan Generation Rules

This document describes the rules applied when PIC constructs, checks, and
displays a trade plan. There are three decision layers:

1. **Convex optimizer:** applies allocation constraints while selecting trades.
2. **Post-trade checks:** re-evaluate the rounded orders, policy rules, and the
   legacy concentration summary.
3. **Plan gate and UI:** combine those results into `PASS`, `WARN`, `ESCALATE`,
   or `BLOCKED`, then display the reasons to the user.

The optimizer proposes an allocation; it does not approve or execute trades.
Manual and rule-based plans also run through the post-trade checks. Generated
plans are returned for PIC review, including plans that are blocked.

Sources: [optimizer.py](../backend/app/optimizer.py),
[planner.py](../backend/app/planner.py),
[policy.py](../backend/app/policy.py), and
[TradePlanner.jsx](../frontend/src/components/TradePlanner.jsx).

## 1. Rules Inside Convex Optimization

Money variables are scaled to crore while solving. Fund mandate limits are
resolved by fund ID from the database when available, with in-code values as
fallbacks. Exposure caps use the projected portfolio and an AUM basis appropriate
to the action. A small solver-scale margin protects against numerical tolerance.

### Buy and contribution: `optimize_buy`

**Objective:** maximize forecast expected return of deployed capital.

| Rule | How it is applied |
|---|---|
| Requested amount | `sum(buy) == amount`; the continuous solution allocates the requested ticket. |
| Long-only | Buy variables cannot be negative. |
| Single issuer | Existing plus proposed issuer value is capped at that fund's database-backed single-issuer limit. |
| Sector | Projected sector value is capped at the active fund's sector limit. |
| Business group | Projected group value is capped at the active fund's group limit. |
| Country | Projected country value is capped at the applicable home, foreign, or emerging-country limit. |
| Cash | Total deployment cannot exceed the policy cash budget: 95% of existing operational cash plus 100% of the new subscription. |
| Diversification | Initially, no name receives more than 34% of the requested buy amount. This is a construction preference, not a compliance limit. |
| Risk | When risk data and a target are supplied, a convex portfolio-volatility ceiling is applied as a preference. |

For a contribution, issuer, sector, group, and country limits use post-contribution
AUM; other buys use current AUM. On infeasibility, the optimizer first relaxes
the 34% per-name diversification cap, then may relax the optional risk ceiling.
The planner's context-aware solve keeps the hard exposure and cash limits. If no
feasible solve is found, the planner falls back to its rule-based path and the
same final checks still apply.

Buy candidates are screened before solving for hard trade exclusions, including
restricted or encumbered securities, configured ESG exclusions, stale prices,
spread above the blocking threshold when ADV data is present, and foreign-
currency exposure above its blocking threshold. Warning-only conditions are not
candidate exclusions.

### Sell and redemption: `optimize_sell`

**Objective:** raise the requested cash while minimizing the forecast return,
exit tax, and transaction cost given up.

| Rule | How it is applied |
|---|---|
| Sellable shares | Each sell is bounded by sellable shares after pending sells and by the minimum-holding requirement. Restricted, encumbered, stale-price, excessive-spread, or over-limit FX positions are not sell candidates. |
| Requested raise | The continuous target is capped by total sellable value. Whole-share rounding can leave a small shortfall. |
| Issuer, sector, group, country | Projected exposure is constrained using the active fund limits and post-redemption AUM basis. |
| Diversification | Initially, each name contributes no more than 34% of the cash target; this preference may be relaxed when capacity is insufficient. |
| Tax and transaction costs | The objective prefers lower-cost exits, including loss lots and LTCG lots where represented by the supplied rates. |
| Risk | A supplied portfolio-volatility ceiling is attempted as a preference and can be relaxed if needed. |

### Rebalance: `optimize_rebalance`

**Objective:** maximize expected return net of estimated exit tax.

| Rule | How it is applied |
|---|---|
| Cash-neutral | Total invested weight remains unchanged before share rounding. |
| Long-only and locked shares | Weights cannot go negative; unsellable shares are preserved. |
| Issuer, sector, group, country | Uses the active fund's limits, not a generic issuer limit. Sector drift is also limited to 2 percentage points from current sector weight. |
| Turnover | `sum(abs(w - w_current)) <= 15%` of AUM. |
| Buy exclusions | A holding marked as blocked for buys cannot be increased. |
| Tax | Selling positions with higher estimated exit costs is penalized. |

After optimization, planner code drops rebalance changes below ₹0.25 Cr and
rounds to whole shares. Sells are capped at available shares and the post-trade
checks evaluate the resulting orders.

### Not hard optimizer constraints

- Liquidity / ADV thresholds produce `WARN` or `ESCALATE`, not `BLOCK`; they are
  evaluated after order construction and do not make the convex solve infeasible.
- The exact UCITS-style 5/40 rule depends on which individual positions cross
  5%, so it remains a post-trade check rather than a continuous convex constraint.
- Watchlist escalation, corporate-event warnings, order-count review, and
  execution-horizon review are post-trade/planning checks.
- Optional volatility targeting is a preference and may be relaxed; the achieved
  risk is reported separately from compliance status.

## 2. Post-Trade Policy Checks

`policy.evaluate()` runs on the proposed, whole-share orders. Projected portfolio
exposures use post-trade AUM. These checks run for optimized, rules-based, and
manual plans. They remain necessary because rounding and order construction can
change the continuous optimizer result.

### Exposure and concentration

| Check | Code | Current rule and outcome |
|---|---|---|
| Single issuer | `MANDATE-ISSUER` | Fund-specific limit; above limit `BLOCK`; within 90% of limit `WARN`. |
| Sector | `MANDATE-SECTOR` | Fund-specific sector limit; above `BLOCK`; within 90% `WARN`. |
| Group | `MANDATE-GROUP` | Fund-specific group limit; above `BLOCK`; within 90% `WARN`. |
| Simplified 5/40 concentration | `UCITS-5-40` | Sum positions individually above 5%; limit 40%; above `BLOCK`, at least 36% `WARN`. This is not a full UCITS eligibility test. |
| Country | `COUNTRY-LIMIT` | Home country 100%; foreign country 35%; emerging country 20% when an existing holding identifies that country as emerging. Above `BLOCK`; within 90% `WARN`. |

For issuer, sector, group, and country checks, an inherited breach that is not
worsened by more than 0.01 percentage points is reported as `WARN` rather than
blocking an unrelated trade.

### Security eligibility and execution

| Check | Code | Outcome |
|---|---|---|
| Restricted or pledged/encumbered security | `RESTRICTED-SECURITY` | `BLOCK` any proposed trade. |
| Internal watchlist | `WATCHLIST-SECURITY` | `ESCALATE` for review. |
| Sell exceeds available shares after pending sells | `RESTRICTED-SELL` | `BLOCK`. |
| Sale breaches minimum holding | `MIN-HOLDING` | `BLOCK`. |
| Valid sell within lock-in restrictions | `LOCK-IN` | `PASS` informational check; only sellable quantity is used. |
| Configured ESG exclusion on a buy | `ESG-EXCLUSION` | `BLOCK` the buy; existing shares are not automatically sold. |
| Thermal-power exposure above 20% on a buy | `ESG-THERMAL-POWER` | `WARN`. |
| Stale price | `PRICE-FRESHNESS` | `BLOCK`. |
| ADV participation | `LIQUIDITY-ADV` | Average daily participation over the requested horizon: >5% `WARN`; >75% `ESCALATE`; missing ADV `ESCALATE`. It is not a hard optimizer cap. |
| Bid-ask spread | `LIQUIDITY-SPREAD` | >0.5% `WARN`; >1% `BLOCK`. |
| Foreign-currency exposure | `FX-EXPOSURE` | >10% `WARN`; >15% `BLOCK`. |
| Corporate-action window | `CORP-ACTION-WINDOW` | Dividend/ex-date within 1 day or another event within 2 days: `WARN`. |

### Cash and plan-level review

| Check | Code | Outcome |
|---|---|---|
| Cash deployment | `CASH-DEPLOYMENT` | Net buys must fit within 95% of existing operational investable cash plus 100% of the new subscription; otherwise `BLOCK`. |
| Number of orders | `PLAN-ORDER-COUNT` | More than 50 `WARN`; more than 100 `ESCALATE`. |
| Execution horizon | `PLAN-HORIZON` | More than 20 days `ESCALATE`. |

### Tax guardrails

These are advisory and do not themselves block a plan.

| Check | Code | Outcome |
|---|---|---|
| Exit tax drag | `TAX-DRAG` | >60 bps `WARN`; >150 bps `ESCALATE`. |
| Short-term gains share of sale value | `TAX-STCG-SHARE` | >50% `WARN`. |
| Losing position retained because exit cost exceeds expected loss | `TAX-HOLD` | `WARN`. |

## 3. Legacy Compliance Summary

`planner._compliance_checks()` separately reports:

| Check | Code | Outcome |
|---|---|---|
| Single issuer | `SEBI-10PCT` | Above limit `FAIL`; at least 90% of limit `WARN`; otherwise `PASS`. |
| Sector | `SECT-35PCT` | Above limit `FAIL`; at least 90% of limit `WARN`; otherwise `PASS`. |
| Group | `GRP-20PCT` | Above limit `FAIL`; at least 90% of limit `WARN`; otherwise `PASS`. |

Any legacy `FAIL` makes `execution_allowed` false, even if `policy_status` is
only `WARN`. The active fund limits are database-backed when available. Current
real-fund data labels each business group with its ticker, so affiliated
companies will not aggregate until the group metadata is populated correctly.

## 4. Final Plan Gate and UI

Backend `plan_gate_status` is an aggregate presentation status:

| Condition | Plan gate | Execution |
|---|---|---|
| Legacy compliance `FAIL` or policy `BLOCK` | `BLOCKED` | Not allowed |
| Otherwise, policy `ESCALATE` | `ESCALATE` | Not allowed; human review required |
| Otherwise, a compliance warning, elevated risk, or policy `WARN` | `WARN` | Allowed, review advised |
| No failure, escalation, or warning | `PASS` | Allowed |

The Trade Planner UI shows the **Plan Gate** chip and the separate compliance
and policy statuses in the summary tile. A `BLOCKED` plan lists each blocking
policy check (rule code, entity, and message) directly under the recommendation
alert. Duplicate legacy failures for an entity already represented by a policy
block are omitted from that inline list. Full legacy checks remain in the
Compliance table; policy warnings, blocks, and escalations appear in the
Execution Risk panel.

## 5. Important Boundaries

- The database thresholds and ESG exclusions are current demo/POC settings, not
  approved legal or fund mandates.
- `min_large_cap_pct` and the fund mandate's configured `max_cash_pct` are
  exposed as configuration but are not currently enforced by the post-trade
  policy. The separate 95% operational-cash deployment rule is enforced.
- Missing or incomplete rule data may trigger escalation or fallback behavior;
  it must not be interpreted as compliance approval.
- Expected returns are supplied by `forecast.predict_returns`; they determine
  optimizer ranking, not whether a policy limit is met.
- The PIC decision endpoint records a review decision; it does not execute
  trades. A plan with `execution_allowed = false` must not be treated as
  executable because someone selected “Approve”.

## Code Locations

| Responsibility | Source |
|---|---|
| Convex allocation objectives and constraints | `backend/app/optimizer.py`: `optimize_buy`, `optimize_sell`, `optimize_rebalance` |
| Candidate preparation, plan assembly, fallback, legacy checks, and plan gate | `backend/app/planner.py`: `_buy_candidates`, `_sell_candidates`, `_orders_by_optimizer`, `_compliance_checks`, `_plan_gate_status` |
| Post-trade policy checks and risk flags | `backend/app/policy.py`: `_concentration_checks`, `_order_checks`, `_tax_checks`, `evaluate` |
| Fund-specific mandate limits | `backend/app/data_v2.py`: `get_fund_compliance_limits` |
| Plan-gate and blocker presentation | `frontend/src/components/TradePlanner.jsx`: Plan Gate summary, inline blocker list, Compliance table, and Execution Risk panel |
