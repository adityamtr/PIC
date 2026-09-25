# Policy Adjustments From This Session

This document records the policy and data changes implemented during the plan
generation review session.

## Objective

Reduce false plan blocks while keeping genuine compliance, ESG, restricted-
security, and issuer-limit failures visible to PIC reviewers.

The final matrix target was to show warnings for schedulable execution issues
and reserve hard blocks for trades that cannot be made compliant.

## Implemented Changes

### Liquidity

- Liquidity is treated as a schedulable execution constraint, not a compliance
  impossibility, so it is judged as **average daily participation over the
  plan's execution horizon**, not the whole parent order against a single day's
  ADV. `daily_participation = order_ADV_pct / horizon_days`.
- Warning above `5%` average daily participation.
- Above `75%` average daily participation the order **escalates** for
  scheduling review; it is no longer a hard block. Even the full horizon at a
  prudent daily cap cannot absorb it, so a PIC reviewer must extend the window
  or split the order.
- The maximum plan horizon before the horizon itself escalates was raised from
  `10` to `20` trading days, so a large parent order can be worked across up to
  four trading weeks and remain executable.
- Estimated ADV uses the smaller of current ADV and median ADV.
- Bid-ask spread checks remain active.

This allows a large parent order to be split across trading sessions without
blocking the entire plan; a genuinely un-workable order surfaces as an
escalation rather than a wall of hard blocks.

### Concentration and Mandate Limits

- Fund-specific limits are now used for real-data funds.
- Projected exposure is measured against the **post-trade AUM** (pre-trade AUM
  plus net new buys, minus sells), not the pre-trade AUM. A contribution brings
  in cash that raises AUM as well as position values; dividing by the pre-trade
  AUM inflated every percentage and manufactured impossible breaches such as
  India country exposure above `100%`. This correction is applied in both the
  policy engine and the planner's separate compliance layer.
- Existing portfolio breaches are reported as warnings when a proposed trade
  does not worsen them.
- A proposed trade that creates or increases a breach remains blocked.
- Home-country exposure is allowed up to `100%` for the India-domiciled funds.
- Foreign-country limits remain `35%`, or `20%` for emerging-market countries.
- UCITS-style aggregate checks remain active.
- Issuer, group, and sector limits were not broadly relaxed.
- The convex optimizer now enforces the fund's own issuer and sector caps as
  hard constraints (against the post-trade AUM), so an automated buy plan never
  proposes a breaching allocation; it allocates up to, but not through, the
  caps. Residual near-limit positions surface as warnings, not blocks.

### Automated Allocation

- Rule-based and optimized buys skip securities with hard ESG or restriction
  exclusions.
- Buy allocation weights are renormalized after excluded securities are removed.
- Manual selections remain subject to hard policy checks so an explicitly
  selected prohibited security is still visible as a failure.

### Restricted Sells

- Pending sell commitments are removed from available sell capacity.
- Automated funding, redemption, rebalance, and optimizer sell candidates use
  pending-adjusted sellable shares.
- Lock-ins, pledged shares, and minimum holding requirements remain hard
  restrictions.

### Cash Deployment

- New subscription cash raised for a contribution is added to the plan's
  investable balance so the plan can actually deploy it. Previously the
  contribution amount was never counted, so any sizeable contribution failed
  the cash-deployment check against pre-existing cash alone.
- The `95%` cash-usage buffer now applies only to pre-existing operational
  cash; the fresh subscription is treated as fully deployable.

### Plan Size and Review

- Plans with `51-100` orders produce warnings and can be split operationally.
- Plans above `100` orders require escalation.
- The recommended UI profile is:
  - Default ticket: `10 Cr` or less.
  - Maximum single parent plan: `50 Cr`.
  - Larger requests: split into child plans with separate execution windows.

## Data Corrections

- Added curated security metadata for both synthetic and disclosure-backed
  holdings.
- Added country, currency, FX, ADV, median ADV, spread, price freshness, lot
  size, restriction, pledge, minimum holding, ESG, and UCITS fields.
- Added corporate-action status, confidence, source, and policy-data dates.
- Replaced invalid disclosure target weights with market-value weights when an
  individual weight or aggregate target total was unrealistic.
- Skipped holdings without valid prices in allocation paths instead of raising
  runtime errors.
- Stopped using industry as a proxy for business-group exposure in disclosure
  data; issuer-level fallback metadata is used instead.

## Matrix Results

The matrix script tests five funds, three allocation modes, and eight scenarios
per mode:

```text
Total cases:       120
Executable:        119 (99.2%)
Warnings:          119
Hard blocks:         1
Escalations:         0
```

Run the matrix with:

```bash
cd backend
python tests/plan_generation_matrix.py
```

## Remaining Hard Failures

Only one matrix case now hard-blocks — a manual order that concentrates a very
large amount into a single security in a small fund:

| Fund | Method | Scenario | Reason |
| --- | --- | --- | --- |
| HDFC Retirement Equity | Manual | `250 Cr` single-name contribution | Issuer, sector, country, and liquidity breach |

This is a genuine over-concentration, not a false block: the manual selection
puts the whole `250 Cr` into one name. Automated (rule-based and optimized)
plans no longer produce this because they spread the deployment and respect the
mandate caps as hard constraints. The manual case should remain visible as a
failure unless the order is spread across securities or converted into a
scheduled multi-day execution plan.

## Large Contribution and Redemption Handling

Large fund flows are now supported as a first-class case: a portfolio manager
can contribute or redeem up to roughly `10%`, `20%`, and `50%` of a fund's AUM
and still receive an executable or reviewable plan.

- Contributions and redemptions up to about `20%` of AUM are executable
  (warnings only) at the default horizon.
- A `50%`-of-AUM contribution is executable once its execution horizon is
  extended (about `15` trading days), which the raised `20`-day horizon ceiling
  now permits; at the default `5`-day horizon it escalates for scheduling
  review because that much cannot be traded prudently in a single week.
- These outcomes depend on the post-trade AUM denominator fix, the
  subscription cash-deployment fix, the horizon-aware liquidity check, and the
  optimizer cap constraints described above.

## Validation

- Backend compilation passed.
- Policy unit tests passed.
- The 120-case plan matrix passed without runtime errors.
- Workspace diagnostics reported no errors in the changed backend files.

## Production Follow-Up

The current metadata is curated POC data. Before production use, replace the
estimated values with approved feeds for:

- ADV, median ADV, and bid-ask spreads.
- Security domicile and look-through country exposure.
- Corporate-action status and settlement state.
- Restricted and watch lists.
- ESG revenue exposure and controversy classifications.
- Price freshness and lot-size rules.

The implemented thresholds are operational defaults, not legal or investment
advice. Compliance and the fund prospectus must approve the final values.