# Trade Plan Policy Rules

This document defines a proposed pre-trade policy framework for plan
generation. The thresholds below are dummy values for the PIC proof of concept
and must be confirmed by Compliance, Legal, the fund prospectus, and the
relevant investment mandate before production use.

The controls are evaluated in the following order:

```text
Fund mandate limits
  -> Liquidity restrictions
  -> Concentration and UCITS limits
  -> Corporate actions
  -> Restricted securities
  -> ESG restrictions
  -> Country limits
  -> Cash-flow planning
  -> Trading plan creation
```

The system should validate the projected portfolio after applying the complete
set of proposed orders, not one order at a time.

## Rule Outcomes

Every rule should return one of these outcomes:

| Outcome | Meaning | Plan behavior |
| --- | --- | --- |
| `PASS` | Rule is satisfied | Continue evaluation |
| `WARN` | Near a limit or data is incomplete | Continue, but add a risk flag and require PIC acknowledgement |
| `BLOCK` | Trade is prohibited or the limit would be breached | Do not include the affected order in an executable plan |
| `ESCALATE` | Policy interpretation or data quality requires human review | Keep the plan pending and route to Compliance or the PIC lead |

Suggested warning bands:

- Warning at `90%` or more of a hard limit.
- Warning at `80%` or more of a soft limit.
- Missing mandatory restriction data produces `ESCALATE`, not `PASS`.

## 1. Fund Mandate Limits

Mandate rules are fund-specific and take precedence over generic defaults.

### Dummy baseline values

| Rule | Dummy threshold | Severity |
| --- | ---: | --- |
| Single issuer exposure | `10%` of NAV | `BLOCK` above limit |
| Business group exposure | `20%` of NAV | `BLOCK` above limit |
| Single sector exposure | `35%` of NAV | `BLOCK` above limit |
| Minimum large-cap exposure for large-cap funds | `80%` of NAV | `BLOCK` below minimum |
| Minimum large-cap exposure for flexi-cap funds | `65%` of NAV | `WARN` below minimum |
| Maximum cash for a normal equity fund | `20%` of NAV | `WARN` above limit; `BLOCK` above `25%` |
| Minimum cash reserve | `1%` of NAV | `BLOCK` if unavailable |
| Maximum portfolio leverage | `0%` | `BLOCK` |
| Derivatives exposure without explicit mandate | `0%` | `BLOCK` |

### Evaluation

1. Identify the fund mandate by `fund_id`.
2. Load the mandate-specific issuer, group, sector, asset-class, cash, and
   leverage limits.
3. Project weights after all proposed buys and sells.
4. Apply the strictest applicable rule when the mandate and a generic rule
   differ.

If mandate metadata is missing, the plan should be `ESCALATE` rather than use a
more permissive default.

## 2. Liquidity Restrictions

Liquidity rules prevent an order from causing unreasonable market impact or
becoming impossible to execute within the requested horizon.

### Dummy thresholds

| Rule | `PASS` | `WARN` | `BLOCK` |
| --- | ---: | ---: | ---: |
| Order value as percentage of ADV | up to `5%` | `>5%` to `75%` | `>75%` |
| Order value as percentage of 20-day median ADV | up to `5%` | `>5%` to `75%` | `>75%` |
| Bid-ask spread | up to `0.50%` | `>0.50%` to `1.00%` | `>1.00%` |
| Minimum average daily traded value | `>= Rs 25 Cr` | `Rs 10-25 Cr` | `< Rs 10 Cr` |
| Maximum participation per trading day | `10%` of ADV | `5%` to `10%` | above `10%` |
| Maximum execution horizon | `<=5` trading days | `6-10` days | `>10` days |

### Order-sizing behavior

- Split a warning-level order over the available execution days. The parent
  plan may use up to `75%` of ADV, while each single-day child order should
  target no more than `10%` of ADV.
- Recalculate participation using the smaller of current ADV and 20-day median
  ADV.
- Block purchases when liquidity data is missing for a security outside the
  approved universe.
- Block a sell when the proposed quantity exceeds available sellable shares.
- Treat an ETF or index constituent as liquid only when its own liquidity data
  passes; index membership alone is insufficient.

## 3. Concentration and UCITS Limits

The following are dummy diversification controls inspired by UCITS-style
concentration rules. They are not a legal interpretation of the UCITS
Directive.

### Dummy UCITS-style values

| Rule | Dummy threshold | Severity |
| --- | ---: | --- |
| Normal single issuer | `5%` of NAV | `BLOCK` above limit |
| Single issuer permitted expansion | up to `10%` of NAV | `WARN`; requires aggregate test |
| Aggregate positions above `5%` | maximum `40%` of NAV | `BLOCK` above limit |
| Single group exposure | `20%` of NAV | `BLOCK` above limit |
| Government issuer exposure | `35%` per issuer | `BLOCK` above limit |
| Unlisted / OTC exposure | `10%` of NAV | `BLOCK` above limit |
| Illiquid securities in aggregate | `10%` of NAV | `BLOCK` above limit |
| Single security ticket size | `34%` of the requested amount | `WARN`; split if possible |
| Rebalance turnover | `15%` of NAV per plan | `WARN` above limit; `BLOCK` above `25%` |

### Aggregate test

For every projected portfolio:

1. Calculate each issuer's post-trade weight.
2. Identify all positions above `5%`.
3. Sum those positions.
4. Block the plan if the sum exceeds `40%` of NAV.

This test must run after both buys and sells. A sale from one security can make
room for another security to increase without breaching the aggregate limit.

## 4. Corporate Actions

Corporate actions can change security ownership, cash, prices, and execution
eligibility. The planner should evaluate them before order creation.

### Dummy timing rules

| Event | Dummy restricted window | Default action |
| --- | --- | --- |
| Earnings announcement | `2` trading days before through `1` day after | `WARN` buys and sells |
| Dividend ex-date | `1` trading day before through ex-date | `WARN` buys; allow sells |
| Merger, demerger, or delisting | `10` trading days before through completion | `BLOCK` new buys |
| Rights issue or tender offer | From announcement through expiry | `ESCALATE` affected security |
| Stock split or bonus issue | `2` trading days before through settlement | `WARN`; recalculate quantity |
| Suspension or trading halt | Until trading resumes | `BLOCK` |

### Cash and quantity treatment

- Include declared cash inflows only when the payment date is inside the
  planning horizon and the amount is confirmed.
- Include pending corporate-action cash as unavailable until settlement.
- Recalculate share quantities after splits, bonuses, mergers, and other ratio
  events.
- Do not use an ex-date price adjustment as spendable cash.
- Add the event, event date, affected order, and required action to the plan.

## 5. Restricted Securities

Restricted-security controls are hard eligibility checks and should run before
optimization.

### Dummy restrictions

| Restriction | Dummy rule | Severity |
| --- | --- | --- |
| Compliance restricted list | No buy or sell | `BLOCK` |
| Internal watch list | No new buy; sell requires review | `ESCALATE` |
| Lock-in shares | Cannot sell before expiry | `BLOCK` affected quantity |
| Pledged or encumbered shares | Cannot sell without release confirmation | `BLOCK` |
| Missing price or stale price older than `1` trading day | Cannot generate executable order | `ESCALATE` |
| Pending settlement shares | Cannot reuse for a new sale | `BLOCK` affected quantity |
| Minimum holding requirement | Preserve required shares or value | `BLOCK` below minimum |

The order quantity must be limited to:

```text
sellable quantity = held quantity
                   - locked quantity
                   - pledged quantity
                   - quantity already committed to pending sells
```

## 6. ESG Restrictions

ESG restrictions are mandate-specific. A fund may use exclusions, thresholds,
or engagement rules; the proof of concept uses exclusions.

### Dummy exclusion policy

| Activity | Dummy threshold | Treatment |
| --- | ---: | --- |
| Tobacco production | Any direct exposure | `BLOCK` buy |
| Tobacco distribution or retail | Revenue above `5%` | `BLOCK` buy |
| Controversial weapons | Any direct exposure | `BLOCK` buy |
| Thermal coal mining | Revenue above `10%` | `BLOCK` buy |
| Coal-based power generation | Revenue above `20%` | `WARN` and require approval |
| Oil sands | Revenue above `5%` | `BLOCK` buy |
| Severe UN Global Compact breach | Active breach | `ESCALATE` |
| ESG data unavailable | No reliable classification | `ESCALATE` for new buys |

For a dummy tobacco exclusion, the security master should contain fields such
as `tobacco_exposure_pct`, `controversial_weapons_flag`, and
`esg_data_as_of`. Existing holdings may be retained and flagged for review, but
new purchases should be blocked.

## 7. Country Limits

Country exposure should use issuer domicile for corporate issuers and the
underlying exposure country for funds and ETFs.

### Dummy thresholds

| Rule | Dummy threshold | Severity |
| --- | ---: | --- |
| Single country exposure | `35%` of NAV | `BLOCK` above limit |
| Emerging-market country exposure | `20%` of NAV | `BLOCK` above limit |
| High-risk / sanctioned country exposure | `0%` | `BLOCK` |
| Unclassified country exposure | `0%` for new buys | `ESCALATE` |
| Foreign-currency exposure without hedge mandate | `10%` of NAV | `WARN` above limit; `BLOCK` above `15%` |
| Foreign-currency exposure with hedge mandate | `25%` of NAV | `WARN` above limit |

Country rules must be calculated on the projected portfolio and must include
look-through exposure for collective investment vehicles when data is
available.

## 8. Cash-Flow Planning

Cash-flow planning determines the amount that can be deployed without
jeopardizing obligations.

### Dummy cash rules

| Rule | Dummy value | Severity |
| --- | ---: | --- |
| Operational reserve | `1.0%` of NAV | Always retained |
| Minimum absolute reserve | `Rs 25 Cr` | Always retained |
| Pending settlement buffer | `100%` of net expected outflow | Always retained |
| Unconfirmed receivables haircut | `50%` | Do not count full value |
| Dividend certainty threshold | `>=90%` confidence | Count as expected inflow |
| Expense buffer | `1.25x` forecast expenses | Always retained |
| Redemption stress reserve | `1.0%` of NAV over the horizon | Always retained |
| Maximum plan cash usage | `95%` of calculated investable cash | `BLOCK` above limit |

Suggested calculation:

```text
available cash = cash on hand
               - operational reserve
               - minimum absolute reserve
               - pending net outflows
               - expense buffer
               - redemption stress reserve
               + confirmed inflows
               + 50% of unconfirmed receivables
```

The maximum deployable amount is the lower of available cash and the proposed
plan amount. A plan that needs funding sells must show those sells explicitly
before any new buys are released.

## 9. Trading Plan Creation

Only orders that pass or are explicitly approved through an escalation should
be included in the final trading plan.

### Required pre-trade sequence

1. Validate the intent and resolve the fund mandate.
2. Build the projected portfolio for the complete order set.
3. Apply mandate, liquidity, concentration, corporate-action, restriction,
   ESG, and country rules.
4. Calculate cash availability and funding sources.
5. Reduce or split orders that exceed liquidity or ticket limits.
6. Round quantities down to whole shares or valid lot sizes.
7. Re-run every rule after rounding.
8. Generate the plan with orders, funding sources, rule results, warnings, and
   unresolved data issues.

### Dummy order-level limits

| Rule | Dummy value | Severity |
| --- | ---: | --- |
| Minimum equity order | `Rs 0.50 Cr` | Ignore below threshold |
| Minimum rebalance order | `Rs 0.25 Cr` | Ignore below threshold |
| Maximum number of securities in one plan | `50` | `ESCALATE` above limit |
| Maximum plan horizon | `10` trading days | `ESCALATE` above limit |
| Required price freshness | `1` trading day | `BLOCK` if stale |
| Required rule-data completeness | `100%` for new buys | `ESCALATE` below threshold |
| Plan expiry | `2` trading days after creation | Revalidate before execution |

### Minimum plan output

Each plan should contain:

- Fund and mandate version.
- Intent and planning horizon.
- Projected portfolio weights.
- Orders with whole-share quantities, prices, values, and execution windows.
- Funding sources and post-trade cash.
- Results for every rule, including `PASS`, `WARN`, `BLOCK`, or `ESCALATE`.
- Data timestamps and missing-data warnings.
- Corporate-action and restricted-security notes.
- ESG and country exposure summaries.
- PIC recommendation and approval status.

## Implementation Notes

The backend now evaluates these policy categories and attaches structured
results to each generated plan. Both synthetic and disclosure-backed security
records include curated fields for country, currency, ADV, median ADV, spread,
price freshness, lot size, restriction status, ESG classification, and FX
exposure.

Values derived from position size or static POC classifications are explicitly
estimates. They must be replaced or reconciled with approved market,
compliance, ESG, and corporate-action feeds before production use. The existing
allocation engine still proposes orders before the policy evaluator runs, so a
blocked plan remains visible for PIC review but has `execution_allowed: false`.