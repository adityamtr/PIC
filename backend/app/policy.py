"""Pre-trade policy checks for generated PIC plans.

The thresholds in this module are deliberately explicit POC defaults. They are
returned with every evaluation so a future mandate/configuration service can
replace them without changing the planner contract.
"""

from __future__ import annotations

from collections import defaultdict

from . import data, data_v2

CRORE = data.CRORE
POLICY_VERSION = "dummy-policy-2026-09"

POLICY_DEFAULTS = {
    "warning_ratio": 0.90,
    "soft_warning_ratio": 0.80,
    "liquidity_warn_adv_pct": 5.0,
    # Parent plans may be split over multiple sessions. A single-day order
    # should still target <=10% ADV; this ceiling applies to the scheduled plan.
    "liquidity_block_adv_pct": 75.0,
    "min_adv_cr": 10.0,
    "min_order_cr": 0.50,
    "min_rebalance_order_cr": 0.25,
    "max_orders": 50,
    # A large parent order is worked across sessions; allow up to four trading
    # weeks before a plan's horizon itself requires escalation.
    "max_horizon_days": 20,
    "max_cash_usage_ratio": 0.95,
    "ucits_single_issuer_pct": 5.0,
    "ucits_aggregate_over_5_pct": 40.0,
    "country_limit_pct": 35.0,
    "emerging_country_limit_pct": 20.0,
    "home_country_limit_pct": 100.0,
    "foreign_currency_warn_pct": 10.0,
    "foreign_currency_block_pct": 15.0,
    "event_warn_days": 2,
    "dividend_warn_days": 1,
}

# Dummy POC exclusion. Existing positions may remain, but new purchases are
# blocked until the mandate provides a reviewed security classification.
ESG_EXCLUSIONS = {
    "ITC": {"activity": "tobacco production", "exposure_pct": 100.0},
}


def _limits(ds: dict) -> dict:
    if ds["id"] in data_v2.FUNDS_V2:
        return data_v2.get_fund_compliance_limits(ds["id"])
    return data.COMPLIANCE_LIMITS


def _entity(ds: dict, ticker: str) -> dict:
    holding = ds["holdings_by_ticker"].get(ticker)
    universe = data.universe_entry(ticker)
    if holding:
        return {
            "ticker": ticker,
            "sector": holding.get("sector", "Unknown"),
            "group": holding.get("group") or holding.get("sector", "Unknown"),
            "group_source": holding.get("group_source", "curated"),
            "country": holding.get("country", "India"),
            "emerging_market": holding.get("emerging_market", False),
            "currency": holding.get("currency", "INR"),
            "adv_cr": holding.get("adv_cr"),
            "median_adv_cr": holding.get("median_adv_cr"),
            "bid_ask_spread_pct": holding.get("bid_ask_spread_pct"),
            "restricted": holding.get("restricted", False),
            "watchlist": holding.get("watchlist", False),
            "pledged_shares": holding.get("pledged_shares", 0),
            "minimum_holding_shares": holding.get("minimum_holding_shares", 0),
            "esg_excluded": holding.get("esg_excluded", False),
            "tobacco_exposure_pct": holding.get("tobacco_exposure_pct", 0),
            "controversial_weapons_exposure_pct": holding.get("controversial_weapons_exposure_pct", 0),
            "thermal_coal_mining_pct": holding.get("thermal_coal_mining_pct", 0),
            "thermal_power_generation_pct": holding.get("thermal_power_generation_pct", 0),
            "fx_exposure_pct": holding.get("fx_exposure_pct", 0),
            "price_stale": holding.get("price_stale", False),
            "holding": holding,
        }
    if universe:
        return {
            "ticker": ticker,
            "sector": universe.get("sector", "Unknown"),
            "group": universe.get("group") or universe.get("sector", "Unknown"),
            "group_source": universe.get("group_source", "curated"),
            "country": universe.get("country", "India"),
            "emerging_market": universe.get("emerging_market", False),
            "currency": universe.get("currency", "INR"),
            "adv_cr": universe.get("adv_cr"),
            "median_adv_cr": universe.get("median_adv_cr"),
            "bid_ask_spread_pct": universe.get("bid_ask_spread_pct"),
            "restricted": universe.get("restricted", False),
            "watchlist": universe.get("watchlist", False),
            "pledged_shares": universe.get("pledged_shares", 0),
            "minimum_holding_shares": universe.get("minimum_holding_shares", 0),
            "esg_excluded": universe.get("esg_excluded", False),
            "tobacco_exposure_pct": universe.get("tobacco_exposure_pct", 0),
            "controversial_weapons_exposure_pct": universe.get("controversial_weapons_exposure_pct", 0),
            "thermal_coal_mining_pct": universe.get("thermal_coal_mining_pct", 0),
            "thermal_power_generation_pct": universe.get("thermal_power_generation_pct", 0),
            "fx_exposure_pct": universe.get("fx_exposure_pct", 0),
            "price_stale": universe.get("price_stale", False),
            "holding": None,
        }
    return {
        "ticker": ticker, "sector": "Unknown", "group": "Unknown",
        "country": "Unknown", "emerging_market": False, "currency": "INR",
        "adv_cr": None, "holding": None,
    }


def _check(code: str, category: str, status: str, entity: str, message: str,
           limit=None, projected=None, current=None) -> dict:
    result = {
        "code": code, "category": category, "status": status, "entity": entity,
        "message": message,
    }
    if limit is not None:
        result["limit"] = limit
    if projected is not None:
        result["projected"] = round(projected, 2)
    if current is not None:
        result["current"] = round(current, 2)
    return result


def _limit_status(projected: float, limit: float, warning_ratio: float) -> str:
    if projected > limit:
        return "BLOCK"
    if projected >= limit * warning_ratio:
        return "WARN"
    return "PASS"


def _incremental_limit_status(projected: float, current: float, limit: float,
                              warning_ratio: float) -> str:
    """Do not block an unrelated trade because of an inherited breach."""
    if projected > limit:
        if current > limit and projected <= current + 0.01:
            return "WARN"
        return "BLOCK"
    if projected >= limit * warning_ratio:
        return "WARN"
    return "PASS"


def _projected(ds: dict, orders: list[dict]) -> tuple[dict, dict, dict, dict]:
    issuer_values = defaultdict(float)
    sector_values = defaultdict(float)
    group_values = defaultdict(float)
    country_values = defaultdict(float)
    for holding in ds["holdings"]:
        value = holding["market_value"]
        entity = _entity(ds, holding["ticker"])
        issuer_values[holding["ticker"]] += value
        sector_values[entity["sector"]] += value
        group_values[entity["group"]] += value
        country_values[entity["country"]] += value
    for order in orders:
        value = order["est_value"] if order["side"] == "BUY" else -order["est_value"]
        entity = _entity(ds, order["ticker"])
        issuer_values[order["ticker"]] += value
        sector_values[entity["sector"]] += value
        group_values[entity["group"]] += value
        country_values[entity["country"]] += value
    return issuer_values, sector_values, group_values, country_values


def _concentration_checks(ds: dict, orders: list[dict], limits: dict) -> list[dict]:
    issuer_values, sector_values, group_values, country_values = _projected(ds, orders)
    pre_aum = ds["aum"]
    # Projected exposure must divide by the post-trade AUM. A contribution adds
    # the deployed cash to AUM and a redemption removes it; dividing by the
    # pre-trade AUM inflates every percentage and manufactures false
    # concentration and country breaches (e.g. India > 100%) for large flows.
    net_flow = (sum(o["est_value"] for o in orders if o["side"] == "BUY")
                - sum(o["est_value"] for o in orders if o["side"] == "SELL"))
    aum = pre_aum + net_flow
    checks = []
    warning_ratio = POLICY_DEFAULTS["warning_ratio"]

    for ticker, value in issuer_values.items():
        projected = max(value, 0) / aum * 100 if aum else 0
        current = ds["holdings_by_ticker"].get(ticker, {}).get("weight", 0)
        limit = limits["single_issuer_limit"]
        checks.append(_check(
            "MANDATE-ISSUER", "fund_mandate",
            _incremental_limit_status(projected, current, limit, warning_ratio),
            ticker, f"{ticker} projected issuer exposure is {projected:.2f}% vs {limit:.2f}%.",
            limit, projected, current,
        ))

    for sector, value in sector_values.items():
        projected = max(value, 0) / aum * 100 if aum else 0
        current = sum(h.get("weight", 0) for h in ds["holdings"] if h.get("sector") == sector)
        limit = limits["sector_soft_limit"]
        checks.append(_check(
            "MANDATE-SECTOR", "fund_mandate",
            _incremental_limit_status(projected, current, limit, warning_ratio),
            sector, f"{sector} projected exposure is {projected:.2f}% vs {limit:.2f}%.",
            limit, projected, current,
        ))

    for group, value in group_values.items():
        projected = max(value, 0) / aum * 100 if aum else 0
        current = sum(h.get("weight", 0) for h in ds["holdings"] if h.get("group") == group)
        limit = limits["group_limit"]
        checks.append(_check(
            "MANDATE-GROUP", "fund_mandate",
            _incremental_limit_status(projected, current, limit, warning_ratio),
            group, f"{group} projected exposure is {projected:.2f}% vs {limit:.2f}%.",
            limit, projected, current,
        ))

    over_five = sum(
        max(value, 0) for value in issuer_values.values()
        if aum and value / aum * 100 > POLICY_DEFAULTS["ucits_single_issuer_pct"]
    ) / aum * 100 if aum else 0
    ucits_limit = POLICY_DEFAULTS["ucits_aggregate_over_5_pct"]
    current_over_five = sum(
        max(holding["market_value"], 0) for holding in ds["holdings"]
        if pre_aum and holding["market_value"] / pre_aum * 100 > POLICY_DEFAULTS["ucits_single_issuer_pct"]
    ) / pre_aum * 100 if pre_aum else 0
    checks.append(_check(
        "UCITS-5-40", "ucits_concentration",
        _incremental_limit_status(over_five, current_over_five, ucits_limit, warning_ratio),
        "aggregate_over_5_pct",
        f"Positions above 5% aggregate to {over_five:.2f}% vs {ucits_limit:.2f}%.",
        ucits_limit, over_five,
    ))

    for country, value in country_values.items():
        projected = max(value, 0) / aum * 100 if aum else 0
        home_country = ds.get("fund", {}).get("domicile_country", "India")
        if country == home_country:
            limit = POLICY_DEFAULTS["home_country_limit_pct"]
        else:
            limit = (POLICY_DEFAULTS["emerging_country_limit_pct"]
                     if any(_entity(ds, h["ticker"])["country"] == country and
                            _entity(ds, h["ticker"])["emerging_market"]
                            for h in ds["holdings"])
                     else POLICY_DEFAULTS["country_limit_pct"])
        current = sum(
            holding.get("weight", 0) for holding in ds["holdings"]
            if _entity(ds, holding["ticker"])["country"] == country
        )
        checks.append(_check(
            "COUNTRY-LIMIT", "country",
            _incremental_limit_status(projected, current, limit, warning_ratio),
            country, f"{country} projected exposure is {projected:.2f}% vs {limit:.2f}%.",
            limit, projected,
        ))
    return checks


def _order_checks(ds: dict, orders: list[dict], cash_flow: dict, horizon_days: int) -> list[dict]:
    checks = []
    for order in orders:
        ticker = order["ticker"]
        entity = _entity(ds, ticker)
        value_cr = order["est_value"] / CRORE
        holding = entity["holding"]

        if entity["restricted"] or entity["pledged_shares"] > 0:
            checks.append(_check(
                "RESTRICTED-SECURITY", "restricted_security", "BLOCK", ticker,
                f"{ticker} is restricted or encumbered and cannot be traded.",
            ))
        elif entity["watchlist"]:
            checks.append(_check(
                "WATCHLIST-SECURITY", "restricted_security", "ESCALATE", ticker,
                f"{ticker} is on the internal watchlist and requires review.",
            ))

        if order["side"] == "SELL" and holding:
            pending_sell_shares = sum(
                trade["shares"] for trade in ds.get("pending_trades", [])
                if trade["ticker"] == ticker and trade["side"] == "SELL"
            )
            available_after_pending = holding.get("sellable_shares", 0) - pending_sell_shares
            held_shares = holding.get(
                "shares", holding.get("sellable_shares", 0) + holding.get("locked_shares", 0)
            )
            if order["shares"] > available_after_pending:
                checks.append(_check(
                    "RESTRICTED-SELL", "restricted_security", "BLOCK", ticker,
                    f"Sell quantity {order['shares']:,} exceeds quantity available after "
                    f"pending sells ({max(available_after_pending, 0):,}).",
                ))
            elif held_shares - order["shares"] < entity["minimum_holding_shares"]:
                checks.append(_check(
                    "MIN-HOLDING", "restricted_security", "BLOCK", ticker,
                    f"Sale would breach the minimum holding of "
                    f"{entity['minimum_holding_shares']:,} shares.",
                ))
            elif holding.get("locked_shares", 0) > 0:
                checks.append(_check(
                    "LOCK-IN", "restricted_security", "PASS", ticker,
                    f"Sell is within sellable quantity; {holding['locked_shares']:,} shares remain locked.",
                ))

        excluded = entity["esg_excluded"] or ticker in ESG_EXCLUSIONS
        if order["side"] == "BUY" and excluded:
            activity = (ESG_EXCLUSIONS.get(ticker, {}).get("activity")
                        or "mandate-excluded ESG activity")
            checks.append(_check(
                "ESG-EXCLUSION", "esg", "BLOCK", ticker,
                f"New purchase blocked: {ticker} has dummy excluded activity ({activity}).",
            ))
        elif order["side"] == "BUY" and entity["thermal_power_generation_pct"] > 20:
            checks.append(_check(
                "ESG-THERMAL-POWER", "esg", "WARN", ticker,
                f"{ticker} has {entity['thermal_power_generation_pct']:.1f}% thermal power exposure.",
                20.0, entity["thermal_power_generation_pct"],
            ))

        if entity["price_stale"]:
            checks.append(_check(
                "PRICE-FRESHNESS", "plan_creation", "BLOCK", ticker,
                f"{ticker} price is stale and cannot support an executable order.",
            ))

        adv_cr = entity.get("adv_cr")
        if adv_cr:
            median_adv_cr = entity.get("median_adv_cr") or adv_cr
            effective_adv_cr = min(adv_cr, median_adv_cr)
            adv_pct = value_cr / effective_adv_cr * 100
            # Liquidity is a schedulable execution constraint, not a compliance
            # impossibility: a parent order is worked across the execution
            # horizon. Judge the average daily participation over that horizon,
            # not the whole parent order against a single day's ADV. Only when
            # even the full horizon cannot absorb the order at a prudent daily
            # cap does it require review (ESCALATE) rather than a hard block.
            daily_pct = adv_pct / max(horizon_days, 1)
            if daily_pct > POLICY_DEFAULTS["liquidity_block_adv_pct"]:
                status = "ESCALATE"
            elif daily_pct > POLICY_DEFAULTS["liquidity_warn_adv_pct"]:
                status = "WARN"
            else:
                status = "PASS"
            checks.append(_check(
                "LIQUIDITY-ADV", "liquidity", status, ticker,
                f"Order is {adv_pct:.2f}% of effective ADV ({effective_adv_cr:.2f} Cr); "
                f"~{daily_pct:.1f}%/day over {horizon_days} day(s).",
                POLICY_DEFAULTS["liquidity_block_adv_pct"], daily_pct,
            ))
            spread = entity.get("bid_ask_spread_pct")
            if spread is not None:
                spread_status = "BLOCK" if spread > 1.0 else ("WARN" if spread > 0.5 else "PASS")
                checks.append(_check(
                    "LIQUIDITY-SPREAD", "liquidity", spread_status, ticker,
                    f"Bid-ask spread is {spread:.2f}%.", 1.0, spread,
                ))
        else:
            checks.append(_check(
                "LIQUIDITY-DATA", "liquidity", "ESCALATE", ticker,
                "ADV data is missing; execution sizing cannot be verified.",
            ))

        fx_exposure = entity["fx_exposure_pct"]
        if fx_exposure > POLICY_DEFAULTS["foreign_currency_block_pct"]:
            fx_status = "BLOCK"
        elif fx_exposure > POLICY_DEFAULTS["foreign_currency_warn_pct"]:
            fx_status = "WARN"
        else:
            fx_status = "PASS"
        checks.append(_check(
            "FX-EXPOSURE", "country", fx_status, ticker,
            f"Foreign-currency exposure is {fx_exposure:.2f}%.",
            POLICY_DEFAULTS["foreign_currency_block_pct"], fx_exposure,
        ))

        for event in ds.get("event_calendar", []):
            if event["ticker"] != ticker:
                continue
            event_name = event["event"].lower()
            window = (POLICY_DEFAULTS["dividend_warn_days"]
                      if "dividend" in event_name or "ex-date" in event_name
                      else POLICY_DEFAULTS["event_warn_days"])
            if event["days_out"] <= window:
                checks.append(_check(
                    "CORP-ACTION-WINDOW", "corporate_action", "WARN", ticker,
                    f"{ticker} has {event['event']} in {event['days_out']} day(s).",
                    window, event["days_out"],
                ))

    buy_value = sum(o["est_value"] for o in orders if o["side"] == "BUY")
    sell_value = sum(o["est_value"] for o in orders if o["side"] == "SELL")
    net_buy = max(buy_value - sell_value, 0)
    # New subscription cash raised specifically for this plan is fully
    # deployable; the 5% buffer is only meant to reserve pre-existing
    # operational cash, not to strand a fresh contribution.
    subscription = cash_flow.get("subscription_amount", 0.0)
    operational = max(cash_flow["investable_amount"] - subscription, 0.0)
    max_cash = operational * POLICY_DEFAULTS["max_cash_usage_ratio"] + subscription
    cash_status = "PASS" if net_buy <= max_cash else "BLOCK"
    checks.append(_check(
        "CASH-DEPLOYMENT", "cash_flow", cash_status, "plan",
        f"Net cash deployment is {net_buy / CRORE:.2f} Cr vs allowed {max_cash / CRORE:.2f} Cr.",
        max_cash / CRORE, net_buy / CRORE,
    ))

    if len(orders) > POLICY_DEFAULTS["max_orders"]:
        status = "ESCALATE" if len(orders) > POLICY_DEFAULTS["max_orders"] * 2 else "WARN"
        checks.append(_check(
            "PLAN-ORDER-COUNT", "plan_creation", status, "plan",
            f"Plan contains {len(orders)} orders; review is required above "
            f"{POLICY_DEFAULTS['max_orders']}.", POLICY_DEFAULTS["max_orders"], len(orders),
        ))
    if horizon_days > POLICY_DEFAULTS["max_horizon_days"]:
        checks.append(_check(
            "PLAN-HORIZON", "plan_creation", "ESCALATE", "plan",
            f"Planning horizon is {horizon_days} days; review is required above "
            f"{POLICY_DEFAULTS['max_horizon_days']} days.",
            POLICY_DEFAULTS["max_horizon_days"], horizon_days,
        ))
    return checks


def evaluate(ds: dict, orders: list[dict], cash_flow: dict, horizon_days: int) -> dict:
    """Evaluate the proposed order set against the dummy policy controls."""
    limits = _limits(ds)
    checks = _concentration_checks(ds, orders, limits)
    checks.extend(_order_checks(ds, orders, cash_flow, horizon_days))
    counts = {status: sum(1 for check in checks if check["status"] == status)
              for status in ("PASS", "WARN", "BLOCK", "ESCALATE")}
    blocking = [check for check in checks if check["status"] == "BLOCK"]
    escalation = [check for check in checks if check["status"] == "ESCALATE"]
    warnings = [
        f"{check['code']}: {check['message']}"
        for check in checks if check["status"] in ("WARN", "ESCALATE")
    ]
    risk_flags = [
        {"type": check["category"], "severity": "HIGH" if check["status"] == "BLOCK" else "MEDIUM",
         "ticker": check["entity"], "message": check["message"]}
        for check in checks if check["status"] in ("WARN", "BLOCK", "ESCALATE")
    ]
    return {
        "policy_version": POLICY_VERSION,
        "limits": limits,
        "checks": checks,
        "summary": counts,
        "status": "BLOCK" if blocking else ("ESCALATE" if escalation else ("WARN" if counts["WARN"] else "PASS")),
        "execution_allowed": not blocking and not escalation,
        "warnings": warnings,
        "risk_flags": risk_flags,
    }


def buy_exclusion_reason(ds: dict, ticker: str) -> str | None:
    """Return a hard buy exclusion so automated allocators can avoid it."""
    entity = _entity(ds, ticker)
    if entity["restricted"] or entity["pledged_shares"] > 0:
        return "restricted or encumbered security"
    if entity["esg_excluded"] or ticker in ESG_EXCLUSIONS:
        return entity.get("esg_exclusion_reason") or ESG_EXCLUSIONS.get(ticker, {}).get(
            "activity", "mandate-excluded ESG activity"
        )
    return None