# Trade Plan Generation Rules

This document describes how the current backend generates trade plans. The
implementation recommends orders for PIC review; it does not execute trades or
automatically reject a plan.

## Request Flow

`POST /api/trade-plan` calls `planner.generate_plan()`.

The planner performs these steps:

1. Selects the requested fund dataset.
2. Normalizes the action, amount, horizon, and target sectors.
3. Calculates cash-flow planning and investable cash.
4. Generates orders using the requested allocation method.
5. Adds the expected return to every order.
6. Runs compliance checks and risk flags.
7. Produces a recommendation and returns the plan with status `Pending PIC Review`.

Relevant implementation:

- [API route](../backend/app/main.py#L170-L175)
- [Plan generator](../backend/app/planner.py#L586-L719)
- [Request schema](../backend/app/schemas.py#L22-L73)

## Defaults and Target Resolution

- Default action: `contribution`.
- Default amount: `0` crore when omitted.
- Default planning horizon: `5` days.
- Default allocation method: `optimize`.
- `targets` takes precedence over `target`.
- Targets are resolved through sector aliases such as `technology`, `banks`,
  `energy`, `fmcg`, `auto`, and `pharma`.
- An unknown target does not fail the request. Targeted buy actions produce a
  warning and no buy orders.

The current resolver maps sectors, not individual security names, even though
the request schema describes `target` more generally.

## Cash-Flow Planning

The planner calculates investable cash as:

```text
investable cash = total cash
                  - reserves
                  + pending settlement net
                  + dividends payable within the horizon
                  - expense accruals
                  + estimated subscriptions
                  - estimated redemptions
```

The result is floored at zero. The calculation includes:

- Cash on hand.
- Regulatory and operational reserves.
- Pending trade cash impacts.
- Corporate actions payable within the horizon.
- Fund expense accruals.
- Estimated subscriptions of `0.08%` of AUM.
- Estimated redemptions of `0.06%` of AUM.

Implementation: [cash-flow planning](../backend/app/planner.py#L98-L125).

Investable cash is used to fund targeted buy actions. It is not currently a
hard constraint for contributions, manual buys, or optimizer contributions.

## Allocation Methods

### Manual

Manual plans use the explicitly selected securities and sides.

- Duplicate `(ticker, side)` selections are removed.
- Unknown securities are skipped.
- Buy orders use the selected crore amount converted to whole shares.
- Sell orders are limited to the holding's sellable shares.
- Locked shares produce a medium lock-in risk note.
- Manual buy orders are not constrained by available cash before generation.
- Manual orders are not capped by issuer, group, or sector limits before
  generation.

Implementation: [_orders_by_manual](../backend/app/planner.py#L445-L508).

### Rule-Based Allocation

The rule-based method is selected explicitly with `method: "rules"`, or used
when optimization is unavailable or fails.

#### Contribution

- Identify holdings below their target weights.
- Fill their aggregate shortfall first.
- Distribute any remainder according to target weights.
- Discard orders smaller than `0.5` crore.

Implementation: [build_contribution](../backend/app/planner.py#L174-L207).

#### Redemption

- Identify holdings above their target weights.
- Trim aggregate excess first.
- Distribute any remaining redemption amount according to current weights.
- Sell only sellable shares.
- Discard orders smaller than `0.5` crore.
- Add a lock-in note when the requested reduction exceeds the sellable value.

Implementation: [build_redemption](../backend/app/planner.py#L210-L250).

#### Rebalance

- Normalize target weights to the currently invested proportion.
- Calculate the difference between normalized target value and current market
  value.
- Ignore changes smaller than `0.25` crore.
- Buy positive differences.
- Sell negative differences, limited to sellable shares.
- Keep the rebalance approximately cash-neutral.

Implementation: [build_rebalance](../backend/app/planner.py#L253-L275).

#### Targeted Increase or Buy

- Split the requested amount evenly across selected sectors.
- Use fixed security allocation weights from `data.BUY_ALLOCATION` when a
  sector has a configured allocation.
- Otherwise distribute across holdings in that sector using current weights.
- If the resulting buy value exceeds investable cash, sell the lowest-weight
  holdings outside the selected sectors to fund the gap.
- Funding sells use sellable shares only.

Implementation: [_orders_by_rules](../backend/app/planner.py#L355-L430).

#### Targeted Decrease or Sell

- Split the amount evenly across selected sectors.
- Within each sector, sell the highest-weight holdings first.
- Sell only sellable shares.
- For untargeted selling, trim the lowest-weight holdings across the book.

## Forecast-Driven Optimization

Optimization is the default method when CVXPY is available. Current forecast
returns are hard-coded placeholders, not live TFT inference:

- Forecast horizon: approximately one month.
- Unknown tickers receive a default expected return of `1%`.
- The optimizer maximizes expected return for buys and rebalances.
- The optimizer minimizes expected return given up for sells.

Implementation: [forecast module](../backend/app/forecast.py#L1-L18).

### Optimized Buy

- Allocate exactly the requested amount in the continuous optimization model.
- Use long-only allocations.
- Keep current value plus new value at or below the issuer cap of `10%` of
  AUM.
- Initially cap each security at `34%` of the requested ticket.
- If the diversification cap makes the problem infeasible, remove that cap.
- Convert continuous allocations to whole shares after solving.

Implementation: [optimize_buy](../backend/app/optimizer.py#L84-L130).

### Optimized Sell

- Consider only holdings with sellable shares and valid prices.
- Raise the requested amount, capped by total sellable value.
- Initially cap each security at `34%` of the amount raised.
- If that cap makes the problem infeasible, remove it.
- Prefer selling securities with the lowest expected return.
- Convert continuous values to whole shares after solving.

Implementation: [optimize_sell](../backend/app/optimizer.py#L140-L205).

### Optimized Rebalance

- Keep the invested proportion unchanged, making the model cash-neutral.
- Require non-negative allocations.
- Apply a `10%` issuer cap.
- Limit L1 turnover to `15%`.
- Maximize forecast expected return.

Implementation: [optimize_rebalance](../backend/app/optimizer.py#L208-L254).

If CVXPY is unavailable or the solver fails, the planner falls back to the
rule-based allocator and adds a warning to the plan.

## Compliance Checks

Compliance is evaluated after orders have already been generated. The current
generic limits are:

| Rule | Limit | Status behavior |
| --- | ---: | --- |
| Single issuer | 10% of AUM | `WARN` at 90% or more; `FAIL` above the limit |
| Business group | 20% of AUM | `WARN` at 90% or more; `FAIL` above the limit |
| Sector | 35% of AUM | `WARN` at 90% or more; `FAIL` above the limit |

The checks project current weight plus positive net order value. Sell orders
reduce the ticker delta but are not independently reported as compliance rows.

Implementation: [_compliance_checks](../backend/app/planner.py#L277-L330).

Compliance results influence the recommendation:

- Any `FAIL`: recommend `MODIFY` or `ESCALATE`.
- Any compliance warning or high-severity risk: recommend careful review and
  approval with monitoring.
- Otherwise: recommend approval.

The result is advisory. A compliance failure does not stop plan generation.

## Risk Flags

Risk flags are generated after allocation:

- **Lock-in:** only sellable shares were used, and a medium warning is added
  when a requested sale exceeds the sellable amount.
- **Liquidity:** orders at or above `25%` of ADV are high severity; orders at
  or above `10%` of ADV are medium severity.
- **Timing:** a medium warning is added when a corporate event occurs within
  the planning horizon.

Implementation: [_risk_flags](../backend/app/planner.py#L332-L353).

## Current Enforcement Gaps

The following behavior is part of the current implementation and should not be
read as a fully enforced compliance policy:

1. Cash availability is not a hard constraint for contributions, manual buys,
   or optimizer contributions.
2. Compliance checks run after allocation and do not prevent invalid orders.
3. Sector checks run only for explicitly resolved target sectors. Contributions
   and rebalances generally have no sector compliance row.
4. Group checks may omit newly purchased universe securities that are not yet
   holdings.
5. Manual orders bypass pre-trade issuer, group, sector, and liquidity limits.
6. The planner uses generic `data.COMPLIANCE_LIMITS` and a fixed 10% optimizer
   cap. Fund-specific limits in `data_v2.FUND_COMPLIANCE_LIMITS` are not used by
   plan generation.
7. The optimizer's initial 34% per-name cap is relaxed when infeasible.
8. Optimizer rebalance sales are clipped to sellable shares after solving, so
   the final whole-share orders may no longer exactly match the optimized
   cash-neutral allocation.
9. Liquidity metadata is now present on both synthetic and disclosure-backed
  holdings, but disclosure-backed ADV and spread values are estimates until a
  market-liquidity feed is connected.
10. Forecast returns are placeholders until the TFT inference path is wired in.

## PIC Review State

Every generated plan starts as `Pending PIC Review`. A reviewer can approve,
modify, reject, or escalate it through the decision endpoint. The system does
not automatically execute an approved plan.

Implementation: [decision route](../backend/app/main.py#L181-L203).