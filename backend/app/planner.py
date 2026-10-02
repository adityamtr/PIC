"""
Trade-plan generation engine (the automated "middle layer"), multi-fund.

Given a fund and a Portfolio Manager's intent, this module:
  1. Performs cash-flow planning (incl. pending settlements) -> investable cash.
  2. Determines funding (from cash, or by trimming holdings if there is a gap).
  3. Generates share-level orders.
  4. Runs compliance checks (SEBI-style concentration limits).
  5. Flags execution risks (lock-ins, liquidity/market impact, event timing).
  6. Produces a recommendation for a PIC associate to review.

It RECOMMENDS. It does not decide — every plan comes back as
"Pending PIC Review" and a human approves/modifies/rejects/escalates it.
"""

from __future__ import annotations

import math
import uuid
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas_market_calendars as mcal

from . import data, data_v2, db, forecast, optimizer, policy, risk_model, tax_lots, tax_rules

CRORE = data.CRORE

# Per-issuer cap (fraction of AUM) the convex optimizer respects up-front, so its
# proposals arrive already inside the SEBI single-issuer limit that the
# compliance rules re-check afterwards.
_ISSUER_CAP_FRAC = data.COMPLIANCE_LIMITS["single_issuer_limit"] / 100

# Square-root market-impact heuristic: estimated cost (bps) = coefficient *
# sqrt(participation), participation = order value / effective ADV. This is a
# standard first-order approximation for how much trading against a stock's own
# volume moves the price against you — not a calibrated execution-cost engine,
# but enough to compare orders/days on a common, money-like scale and to give
# the PIC reviewer an indicative ₹ cost instead of a dimensionless ratio.
_IMPACT_COEF_BPS = 15.0

# Indian equity cash-market settlement is T+1 (one trading session after the
# trade). Used only to sanity-check a PM-supplied settlement_date against the
# real calendar — see _check_settlement_window. These never block a plan: per
# product guidance, large contribution/redemption plans must stay executable,
# not hard-blocked, so an odd-looking window is surfaced as a warning only.
_EXPECTED_SETTLEMENT_SESSIONS = 1
_MAX_REASONABLE_SETTLEMENT_SESSIONS = 5

_SECTOR_ALIASES = {
    "technology": "Information Technology", "tech": "Information Technology",
    "it": "Information Technology", "information technology": "Information Technology",
    "software": "Information Technology", "financials": "Financial Services",
    "financial services": "Financial Services", "banking": "Financial Services",
    "banks": "Financial Services", "energy": "Energy", "oil & gas": "Energy",
    "fmcg": "FMCG", "consumer staples": "FMCG", "auto": "Automobile",
    "automobile": "Automobile", "healthcare": "Healthcare", "pharma": "Healthcare",
}


def resolve_sector(target):
    if not target:
        return None
    return _SECTOR_ALIASES.get(target.strip().lower())


def _get_ds(fund_id):
    if fund_id in data_v2.FUNDS_V2:
        return data_v2.get_ds(fund_id)
    return data.get_ds(fund_id)


# --------------------------------------------------------------------------- #
# Price / name / sector helpers (universe first, then the fund's holdings)
# --------------------------------------------------------------------------- #
def _price_for(ds, ticker):
    u = data.universe_entry(ticker)
    if u:
        return u["price"]
    h = data.holding(ds, ticker)
    return h["price"] if h else 0.0


def _name_for(ds, ticker):
    u = data.universe_entry(ticker)
    if u:
        return u["name"]
    h = data.holding(ds, ticker)
    return h["name"] if h else ticker


def _sector_for(ds, ticker):
    u = data.universe_entry(ticker)
    if u:
        return u["sector"]
    h = data.holding(ds, ticker)
    return h["sector"] if h else "Unknown"


def _order(ds, ticker, side, rupees=None, shares=None):
    holding = data.holding(ds, ticker) if side == "SELL" else None
    holding_price = holding.get("price") if holding else None
    price = holding_price if _usable_price(holding_price) else _price_for(ds, ticker)
    if shares is None:
        shares = int(rupees // price) if price else 0
    return {
        "ticker": ticker, "name": _name_for(ds, ticker), "sector": _sector_for(ds, ticker),
        "side": side, "shares": shares, "price": price, "est_value": shares * price,
    }


def _market_impact_bps(value_cr, effective_adv_cr):
    """Square-root market-impact estimate in bps for trading `value_cr` crore
    against an `effective_adv_cr` crore average daily volume. See the
    `_IMPACT_COEF_BPS` module note for what this model does and doesn't capture."""
    if not effective_adv_cr or value_cr <= 0:
        return 0.0
    participation = value_cr / effective_adv_cr
    return _IMPACT_COEF_BPS * math.sqrt(participation)


def _check_settlement_window(trade_date, settlement_date):
    """Sanity-check a PM-supplied settlement_date against the real NSE/BSE
    calendar instead of trusting it as-is. Indian equity settlement is T+1 (one
    trading session after the trade). Only ever returns warnings — see the
    `_EXPECTED_SETTLEMENT_SESSIONS` module note on why this doesn't block."""
    if settlement_date <= trade_date:
        return [f"Settlement date {settlement_date.isoformat()} is not after trade date "
                f"{trade_date.isoformat()} — standard T+1 settlement needs at least one "
                "trading session between them; orders will use the trade date as-is instead "
                "of a multi-day schedule."]
    try:
        session_range = {"start_date": trade_date, "end_date": settlement_date}
        sessions = mcal.get_calendar("NSE").valid_days(**session_range).intersection(
            mcal.get_calendar("BSE").valid_days(**session_range)
        ).date.tolist()
    except Exception:
        return []
    gap_sessions = len([d for d in sessions if trade_date < d <= settlement_date])
    if gap_sessions < _EXPECTED_SETTLEMENT_SESSIONS:
        return [f"No NSE/BSE trading session falls between {trade_date.isoformat()} and "
                f"settlement date {settlement_date.isoformat()} — standard T+1 settlement "
                "is not achievable in this window."]
    if gap_sessions > _MAX_REASONABLE_SETTLEMENT_SESSIONS:
        return [f"Settlement window spans {gap_sessions} trading sessions, well beyond the "
                "standard T+1 cycle — confirm the settlement date is intentional."]
    return []


def _committed_daily_load(trading_dates):
    """Market-impact load (in the same bps-equivalent units as
    `_market_impact_bps`) that *other* stored plans have already booked on
    these sessions, so a new plan's greedy balance can see — and route around
    — volume other plans have already committed to a given day. Liquidity is a
    market-wide resource (a stock's ADV doesn't care which fund trades it), so
    this looks across every stored plan, not just the current fund's.

    Uses the static universe ADV rather than loading every other plan's own
    fund dataset — a deliberate approximation for what is only an
    informational, non-blocking signal. Degrades to "nothing committed"
    (returns {}) if plan storage is unavailable, matching db.py's
    fail-open contract so scheduling still works without a DB.
    """
    load = {day: 0.0 for day in trading_dates}
    if not trading_dates:
        return load
    try:
        plans = db.list_plans() or []
    except Exception:
        return load
    window = {day.isoformat(): day for day in trading_dates}
    for plan in plans:
        if str(plan.get("status", "")).strip().lower() == "rejected":
            continue  # a rejected plan's orders will never actually trade
        for order in plan.get("orders", []):
            day = window.get(order.get("trade_date"))
            if day is None:
                continue
            universe_entry = data.universe_entry(order.get("ticker") or "")
            adv_cr = universe_entry.get("adv_cr") if universe_entry else None
            value_cr = float(order.get("est_value") or 0) / CRORE
            load[day] += _market_impact_bps(value_cr, adv_cr)
    return load


def _schedule_order_trade_dates(ds, orders, returns, trade_date, settlement_date):
    """Suggest regular-session dates for each order:
      - balancing orders across days by estimated market-impact cost (bps),
        seeded with load other pending plans have already booked that day;
      - steering higher-conviction orders (larger |expected return|) to the
        lightest-loaded day first, so urgency — not just liquidity — drives
        who gets first pick of a day;
      - avoiding a ticker's own known event date where another session in the
        window allows it.
    """
    session_range = {
        "start_date": trade_date,
        "end_date": settlement_date - timedelta(days=1),
    }
    trading_dates = mcal.get_calendar("NSE").valid_days(**session_range).intersection(
        mcal.get_calendar("BSE").valid_days(**session_range)
    ).date.tolist()

    if not trading_dates:
        return [
            "No regular NSE trading session falls between the selected trade and "
            "settlement dates; order trade dates were not suggested."
        ]

    def effective_adv_cr(order):
        entity = policy._entity(ds, order["ticker"])
        adv_cr = entity.get("adv_cr")
        median_adv_cr = entity.get("median_adv_cr") or adv_cr
        return min(adv_cr, median_adv_cr) if adv_cr and median_adv_cr else None

    def impact_bps(order):
        value_cr = float(order.get("est_value") or 0) / CRORE
        return _market_impact_bps(value_cr, effective_adv_cr(order))

    def event_date_to_avoid(order):
        ev = data.event_for(ds, order["ticker"])
        if not ev:
            return None
        ev_date = date.fromisoformat(ev["event_date"])
        return ev_date if ev_date in trading_dates else None

    def expected_return(order):
        return abs(returns.get(order["ticker"]) or forecast.expected_return(order["ticker"]) or 0)

    ordered = sorted(
        orders,
        key=lambda order: (
            order.get("side") != "SELL",
            -expected_return(order),
            order.get("ticker", ""),
        ),
    )

    warnings = []
    daily_load = _committed_daily_load(trading_dates)
    for order in ordered:
        avoid = event_date_to_avoid(order)
        candidates = [day for day in trading_dates if day != avoid] or trading_dates
        selected_date = min(candidates, key=lambda day: (daily_load[day], day))
        if avoid is not None and selected_date == avoid:
            ev = data.event_for(ds, order["ticker"])
            warnings.append(
                f"{order['ticker']}: no trading session avoids {ev['event']} on "
                f"{ev['event_date']} within this window — order was still scheduled on it."
            )
        cost_bps = impact_bps(order)
        order["trade_date"] = selected_date.isoformat()
        order["est_impact_bps"] = round(cost_bps, 1)
        order["est_impact_cost"] = round(cost_bps / 10_000 * float(order.get("est_value") or 0), 0)
        daily_load[selected_date] += cost_bps

    return warnings


def _usable_price(price):
    return isinstance(price, (int, float)) and math.isfinite(price) and price > 0


def _approved_sent_plans(fund_id):
    """Plans for this fund that are both approved *and* have sent emails (i.e.
    execution instructions were actually sent) — real market commitments, as
    opposed to "Pending PIC Review" / "Returned for Modification" / "Rejected"
    / "Escalated" plans that never left the building.

    Returns an empty list if DB is unavailable or no such plans exist. Never
    raises; degradation is graceful per db.py's fail-open contract."""
    try:
        plans = db.list_plans(fund_id) or []
    except Exception:
        return []

    out = []
    for plan in plans:
        status_str = str(plan.get("status", "")).lower()
        if not any(s in status_str for s in ["approved", "sent to trading"]):
            continue
        try:
            sent_emails = db.list_sent_emails(plan.get("plan_id")) or []
            if not sent_emails:
                continue
        except Exception:
            # If we can't check email status, don't include the plan (safer)
            continue
        out.append(plan)
    return out


def _fy_start(as_of):
    """Indian financial year start (Apr 1) covering `as_of`."""
    year = as_of.year if as_of.month >= 4 else as_of.year - 1
    return date(year, 4, 1)


def _ltcg_exemption_used_this_fy(fund_id, as_of):
    """Rs 1.25L LTCG exemption already consumed by this fund's approved+sent
    plans so far this financial year, so a later plan in the same FY doesn't
    apply the full exemption again."""
    fy_start = _fy_start(as_of)
    used = 0.0
    for plan in _approved_sent_plans(fund_id):
        created_at = plan.get("created_at")
        try:
            created_date = datetime.fromisoformat(created_at).date() if created_at else None
        except (ValueError, TypeError):
            created_date = None
        if not created_date or created_date < fy_start:
            continue
        used += (plan.get("tax_summary") or {}).get("ltcg_exemption_used_inr", 0.0) or 0.0
    return used


def _consumed_tax_lots_by_ticker(fund_id):
    """{ticker: {lot_id: shares_already_sold}} from approved+sent plans'
    SELL orders, so a later plan doesn't attribute a sale against lot shares
    that a prior executed plan already consumed (lots are read fresh from the
    synthetic universe on every plan, so without this a lot could be "sold"
    by two different plans)."""
    consumed: dict[str, dict[str, int]] = {}
    for plan in _approved_sent_plans(fund_id):
        for order in plan.get("orders", []):
            if order.get("side") != "SELL":
                continue
            for lot in (order.get("tax") or {}).get("lots_consumed", []):
                lot_id, shares = lot.get("lot_id"), lot.get("shares")
                if not lot_id or not shares:
                    continue
                by_lot = consumed.setdefault(order["ticker"], {})
                by_lot[lot_id] = by_lot.get(lot_id, 0) + shares
    return consumed


def _augment_pending_trades_from_approved_plans(fund_id):
    """Fetch orders from approved, emailed plans in the DB and convert them to
    pending-trade format so they reduce investable cash and sellable shares for
    subsequent plans."""
    approved_trades = []
    for plan in _approved_sent_plans(fund_id):
        for order in plan.get("orders", []):
            ticker = order.get("ticker")
            side = order.get("side")
            shares = order.get("shares")
            price = order.get("price")

            if not all([ticker, side, shares, price]):
                continue

            gross = shares * price
            trade_date_str = order.get("trade_date")
            settlement_date_str = order.get("settlement_date")

            if not (trade_date_str and settlement_date_str):
                continue

            try:
                td = date.fromisoformat(trade_date_str)
                sd = date.fromisoformat(settlement_date_str)
                settlement_days = (sd - td).days
            except (ValueError, TypeError):
                continue

            # Lookup ticker name from universe; fall back to ticker itself if not found
            u = data.universe_entry(ticker)
            name = u.get("name") if u else ticker
            approved_trades.append({
                "trade_id": f"{plan['plan_id']}-{ticker}",
                "ticker": ticker, "name": name, "side": side,
                "shares": shares, "price": price, "gross_value": gross,
                "cash_impact": -gross if side == "BUY" else gross,
                "trade_date": trade_date_str,
                "settlement_date": settlement_date_str,
                "settlement_days": settlement_days,
                "cycle": f"T+{settlement_days}",
                "status": f"Approved (Plan {plan['plan_id']})",
            })

    return approved_trades


def _available_sellable_shares(ds, holding):
    pending_sells = sum(
        trade["shares"] for trade in ds.get("pending_trades", [])
        if trade["ticker"] == holding["ticker"] and trade["side"] == "SELL"
    )
    return max(holding.get("sellable_shares", 0) - pending_sells, 0)


# --------------------------------------------------------------------------- #
# 1. Cash-flow planning
# --------------------------------------------------------------------------- #
def cash_flow_planning(ds, horizon_days):
    total_cash = ds["cash"]["total_cash"]
    reserves = ds["cash"]["reserves"]
    pending_net = sum(t["cash_impact"] for t in ds["pending_trades"])
    dividends = sum(ca["cash_amount"] for ca in ds["corporate_actions"]
                    if ca["pay_offset_days"] <= horizon_days)
    expenses = (ds["fund_expense"].get("daily_accrual") or 0.0) * horizon_days
    est_subs = 0.0008 * ds["aum"]
    est_reds = 0.0006 * ds["aum"]
    net_flows = est_subs - est_reds
    investable = total_cash - reserves + pending_net + dividends - expenses + net_flows
    return {
        "horizon_days": horizon_days,
        "total_cash": total_cash, "reserves": reserves,
        "pending_settlement_net": pending_net, "expected_dividends": dividends,
        "expected_expenses": -expenses, "estimated_subscriptions": est_subs,
        "estimated_redemptions": -est_reds, "investable_amount": max(investable, 0.0),
        "line_items": [
            {"label": "Total cash on hand", "amount": total_cash},
            {"label": "Less: reserves / minimum buffer", "amount": -reserves},
            {"label": "Pending trade settlements (net)", "amount": pending_net},
            {"label": f"Dividend inflows (<= {horizon_days}d)", "amount": dividends},
            {"label": f"Expense accrual ({horizon_days}d)", "amount": -expenses},
            {"label": "Est. net subscriptions/redemptions", "amount": net_flows},
        ],
    }


# --------------------------------------------------------------------------- #
# Order builders
# --------------------------------------------------------------------------- #
def _build_buy_orders(ds, sector, amount):
    alloc = data.BUY_ALLOCATION.get(sector)
    orders = []
    if alloc:
        eligible = [(ticker, frac) for ticker, frac in alloc.items()
                    if policy.buy_exclusion_reason(ds, ticker) is None]
        total_frac = sum(frac for _, frac in eligible) or 1.0
        for ticker, frac in eligible:
            o = _order(ds, ticker, "BUY", rupees=amount * frac / total_frac)
            if o["shares"] > 0:
                orders.append(o)
    else:
        names = [h for h in ds["holdings"] if h["sector"] == sector
                 and policy.buy_exclusion_reason(ds, h["ticker"]) is None]
        total_w = sum(h["weight"] for h in names) or 1.0
        for h in names:
            o = _order(ds, h["ticker"], "BUY", rupees=amount * h["weight"] / total_w)
            if o["shares"] > 0:
                orders.append(o)
    return orders


def _funding_sells(ds, gap, exclude_sectors=None):
    exclude = set(exclude_sectors or [])
    # Lowest-conviction (weight) first; between similar weights prefer the
    # cheaper-tax exit so the rules path is not tax-blind.
    candidates = sorted((h for h in ds["holdings"] if h["sector"] not in exclude),
                        key=lambda h: (round(h["weight"], 1),
                                       h.get("effective_tax_rate_pct") or 0.0))
    sources, notes, remaining = [], [], gap
    for h in candidates:
        if remaining <= 0:
            break
        available_shares = _available_sellable_shares(ds, h)
        if not _usable_price(h["price"]) or available_shares <= 0:
            continue
        sellable_value = available_shares * h["price"]
        shares = int(min(remaining, sellable_value) // h["price"])
        if shares <= 0:
            continue
        value = shares * h["price"]
        sources.append({"ticker": h["ticker"], "name": h["name"], "sector": h["sector"],
                        "side": "SELL", "shares": shares, "price": h["price"],
                        "est_value": value, "reason": "Trim lowest-conviction position to fund purchase"})
        if h["locked_shares"] > 0:
            notes.append({"type": "lock_in", "severity": "MEDIUM", "ticker": h["ticker"],
                          "message": f"{h['ticker']} has {h['locked_shares']:,} locked shares (expiry {h['lock_in_expiry']}); only sellable shares used."})
        remaining -= value
    return sources, notes


def build_contribution(ds, amount):
    """
    Deploy an inflow: first top up under-weight names (below target) toward
    target, then spread any remainder across the book pro-rata to target
    weights. Produces a clean, well-diversified deployment.
    """
    aum = ds["aum"]
    rupees = {h["ticker"]: 0.0 for h in ds["holdings"]}

    eligible_holdings = [h for h in ds["holdings"]
                         if policy.buy_exclusion_reason(ds, h["ticker"]) is None]
    shortfalls = [(h, (h["target_weight"] - h["weight"]) / 100 * aum)
                  for h in eligible_holdings if h["weight"] < h["target_weight"]]
    total_short = sum(s for _, s in shortfalls)
    fill = min(amount, total_short)
    if total_short > 0:
        for h, short in shortfalls:
            rupees[h["ticker"]] += fill * short / total_short

    remaining = amount - fill
    if remaining > 1:
        tw_total = sum(h["target_weight"] for h in eligible_holdings) or 1.0
        for h in eligible_holdings:
            rupees[h["ticker"]] += remaining * h["target_weight"] / tw_total

    min_ticket = 0.5 * CRORE
    orders = []
    for tk, r in sorted(rupees.items(), key=lambda x: x[1], reverse=True):
        if r < min_ticket or not _usable_price(_price_for(ds, tk)):
            continue
        shares = int(r // _price_for(ds, tk))
        if shares > 0:
            orders.append(_order(ds, tk, "BUY", shares=shares))
    return orders, []


def build_redemption(ds, amount):
    """
    Raise cash for a payout: first trim over-weight names (above target) toward
    target, then spread any remainder pro-rata to current weight. Respects
    lock-ins (only sellable shares can be raised).
    """
    aum = ds["aum"]
    rupees = {h["ticker"]: 0.0 for h in ds["holdings"]}

    excesses = [(h, (h["weight"] - h["target_weight"]) / 100 * aum)
                for h in ds["holdings"] if h["weight"] > h["target_weight"]]
    total_excess = sum(e for _, e in excesses)
    take = min(amount, total_excess)
    if total_excess > 0:
        for h, exc in excesses:
            rupees[h["ticker"]] += take * exc / total_excess

    remaining = amount - take
    if remaining > 1:
        w_total = sum(h["weight"] for h in ds["holdings"]) or 1.0
        for h in ds["holdings"]:
            rupees[h["ticker"]] += remaining * h["weight"] / w_total

    min_ticket = 0.5 * CRORE
    orders, notes = [], []
    for h in sorted(ds["holdings"], key=lambda x: rupees[x["ticker"]], reverse=True):
        r = rupees[h["ticker"]]
        if r < min_ticket or not _usable_price(h["price"]):
            continue
        sellable_value = _available_sellable_shares(ds, h) * h["price"]
        shares = int(min(r, sellable_value) // h["price"])
        if shares <= 0 or shares * h["price"] < min_ticket:
            continue
        orders.append(_order(ds, h["ticker"], "SELL", shares=shares))
        if h["locked_shares"] > 0 and r > sellable_value:
            notes.append({"type": "lock_in", "severity": "MEDIUM", "ticker": h["ticker"],
                          "message": f"{h['ticker']} sell capped by lock-in ({h['locked_shares']:,} shares locked)."})
    return orders, notes


def build_rebalance(ds):
    # Normalise targets to the currently-invested proportion so a rebalance
    # only corrects relative drift and stays (near) cash-neutral, rather than
    # forcing the cash level to a particular number.
    invested_weight = sum(h["weight"] for h in ds["holdings"])
    tw_sum = sum(h["target_weight"] for h in ds["holdings"]) or 1.0
    scale = invested_weight / tw_sum
    min_ticket = 0.25 * CRORE
    orders, notes = [], []
    for h in ds["holdings"]:
        if policy.buy_exclusion_reason(ds, h["ticker"]) is not None:
            continue
        if not _usable_price(h["price"]):
            continue
        delta = h["target_weight"] * scale / 100 * ds["aum"] - h["market_value"]
        if abs(delta) < min_ticket:
            continue
        if delta > 0:
            shares = int(delta // h["price"])
            if shares > 0:
                orders.append(_order(ds, h["ticker"], "BUY", shares=shares))
        else:
            sellable_value = _available_sellable_shares(ds, h) * h["price"]
            shares = int(min(-delta, sellable_value) // h["price"])
            if shares > 0:
                orders.append(_order(ds, h["ticker"], "SELL", shares=shares))
                if h["locked_shares"] > 0 and -delta > sellable_value:
                    notes.append({"type": "lock_in", "severity": "MEDIUM", "ticker": h["ticker"],
                                  "message": f"{h['ticker']} target sell capped by lock-in ({h['locked_shares']:,} shares locked)."})
    return orders, notes


# --------------------------------------------------------------------------- #
# 4. Compliance checks
# --------------------------------------------------------------------------- #
def _compliance_checks(ds, orders, sectors=None):
    aum = ds["aum"]
    lim = (data_v2.get_fund_compliance_limits(ds["id"])
           if ds["id"] in data_v2.FUNDS_V2 else data.COMPLIANCE_LIMITS)
    checks = []

    delta = {}
    for o in orders:
        sign = 1 if o["side"] == "BUY" else -1
        delta[o["ticker"]] = delta.get(o["ticker"], 0.0) + sign * o["est_value"]

    # Projected weights must divide by the post-trade AUM. New subscription cash
    # deployed by a contribution raises AUM as well as the position value; using
    # the pre-trade AUM inflates projected weights and manufactures false
    # issuer/sector/group breaches on large flows.
    net_flow = sum(delta.values())
    post_aum = aum + net_flow if aum + net_flow > 0 else aum

    def proj_pct(current_weight, value_delta):
        current_value = current_weight / 100.0 * aum
        return round((current_value + value_delta) / post_aum * 100, 2)

    def st(projected, limit):
        return "FAIL" if projected > limit else ("WARN" if projected >= 0.9 * limit else "PASS")

    for ticker, d in delta.items():
        if d <= 0:
            continue
        h = data.holding(ds, ticker)
        current = h["weight"] if h else 0.0
        projected = proj_pct(current, d)
        checks.append({"code": "SEBI-10PCT", "rule": "Single issuer limit", "entity": ticker,
                       "current": current, "projected": projected, "limit": lim["single_issuer_limit"],
                       "status": st(projected, lim["single_issuer_limit"]),
                       "message": f"{ticker} projected weight {projected}% vs limit {lim['single_issuer_limit']}%."})

    for sector in (sectors or []):
        buy_into = sum(d for tk, d in delta.items() if d > 0 and _sector_for(ds, tk) == sector)
        current = data.sector_weight(ds, sector)
        projected = proj_pct(current, buy_into)
        checks.append({"code": "SECT-35PCT", "rule": "Sector concentration limit", "entity": sector,
                       "current": current, "projected": projected, "limit": lim["sector_soft_limit"],
                       "status": st(projected, lim["sector_soft_limit"]),
                       "message": f"{sector} projected weight {projected}% vs limit {lim['sector_soft_limit']}%."})

    group_delta = {}
    for ticker, d in delta.items():
        if d <= 0:
            continue
        h = data.holding(ds, ticker)
        if h and h["group"]:
            group_delta[h["group"]] = group_delta.get(h["group"], 0.0) + d
    for grp, d in group_delta.items():
        current = data.group_weight(ds, grp)
        projected = proj_pct(current, d)
        status = st(projected, lim["group_limit"])
        if status != "PASS":
            checks.append({"code": "GRP-20PCT", "rule": "Group exposure limit", "entity": grp,
                           "current": current, "projected": projected, "limit": lim["group_limit"],
                           "status": status,
                           "message": f"{grp} projected weight {projected}% vs limit {lim['group_limit']}%."})
    return checks


# --------------------------------------------------------------------------- #
# 5. Risk flags
# --------------------------------------------------------------------------- #
def _risk_flags(ds, orders, extra_notes, horizon_days):
    flags = list(extra_notes)
    for o in orders:
        u = data.universe_entry(o["ticker"])
        if u and u.get("adv_cr"):
            adv = u["adv_cr"] * CRORE
            pct = o["est_value"] / adv * 100 if adv else 0
            if pct >= 25:
                flags.append({"type": "liquidity", "severity": "HIGH", "ticker": o["ticker"],
                              "message": f"{o['ticker']} order is {pct:.1f}% of ADV — high market impact, work over multiple days."})
            elif pct >= 10:
                flags.append({"type": "liquidity", "severity": "MEDIUM", "ticker": o["ticker"],
                              "message": f"{o['ticker']} order is {pct:.1f}% of ADV — moderate market impact."})
        ev = data.event_for(ds, o["ticker"])
        if ev and ev["days_out"] <= horizon_days:
            flags.append({"type": "timing", "severity": "MEDIUM", "ticker": o["ticker"],
                          "message": f"{o['ticker']}: {ev['event']} on {ev['event_date']} — consider timing around the event."})
    return flags


# --------------------------------------------------------------------------- #
# Order generation — rule-based (the original heuristics)
# --------------------------------------------------------------------------- #
def _orders_by_rules(ds, action, sectors, amount, investable, target):
    orders, funding_sources, risk_notes, warnings = [], [], [], []

    if action == "contribution":
        orders, notes = build_contribution(ds, amount)
        risk_notes.extend(notes)
        funding_sources = [{"ticker": "INFLOW", "name": "Contribution / subscription inflow",
                            "sector": "Cash", "side": "IN", "shares": 0, "price": 0,
                            "est_value": amount, "reason": "New cash deployed to under-weight holdings toward target."}]
    elif action == "redemption":
        orders, notes = build_redemption(ds, amount)
        risk_notes.extend(notes)
        raised = sum(o["est_value"] for o in orders if o["side"] == "SELL")
        funding_sources = [{"ticker": "OUTFLOW", "name": "Redemption / payout",
                            "sector": "Cash", "side": "OUT", "shares": 0, "price": 0,
                            "est_value": raised, "reason": "Cash raised by trimming over-weight holdings to fund payout."}]
    elif action == "rebalance":
        orders, notes = build_rebalance(ds)
        risk_notes.extend(notes)
    elif action in ("increase", "buy", "add"):
        if not sectors:
            warnings.append(f"Could not map target '{target}' to a known sector; no buy orders generated.")
        else:
            # Split the amount evenly across the selected sectors.
            per_sector = amount / len(sectors)
            for s in sectors:
                orders.extend(_build_buy_orders(ds, s, per_sector))
            buy_total = sum(o["est_value"] for o in orders)
            if len(sectors) > 1:
                warnings.append(f"Amount split evenly across {len(sectors)} sectors "
                                f"(~Rs {per_sector / CRORE:,.1f} Cr each): {', '.join(sectors)}.")
            gap = buy_total - investable
            if gap > 0:
                sells, notes = _funding_sells(ds, gap, exclude_sectors=sectors)
                funding_sources, orders = sells, orders + sells
                risk_notes.extend(notes)
                warnings.append(f"Purchase exceeds investable cash by ~Rs {gap / CRORE:,.1f} Cr; funded by trimming holdings.")
            else:
                funding_sources = [{"ticker": "CASH", "name": "Available cash", "sector": "Cash",
                                    "side": "USE", "shares": 0, "price": 0, "est_value": buy_total,
                                    "reason": "Fully funded from investable cash."}]
    elif action in ("decrease", "sell", "trim", "raise_cash"):
        if sectors and action in ("decrease", "sell", "trim"):
            # Trim each selected sector by its share of the total amount.
            per_sector = amount / len(sectors)
            for s in sectors:
                names = sorted((h for h in ds["holdings"] if h["sector"] == s),
                               key=lambda h: h["weight"], reverse=True)
                remaining = per_sector
                for h in names:
                    if remaining <= 0:
                        break
                    available_value = _available_sellable_shares(ds, h) * h["price"]
                    shares = int(min(remaining, available_value) // h["price"])
                    if shares <= 0:
                        continue
                    orders.append({**_order(ds, h["ticker"], "SELL", shares=shares),
                                   "reason": f"Reduce {s} exposure"})
                    remaining -= shares * h["price"]
            if len(sectors) > 1:
                warnings.append(f"Reduction split evenly across {len(sectors)} sectors "
                                f"(~Rs {per_sector / CRORE:,.1f} Cr each): {', '.join(sectors)}.")
        else:
            sells, notes = _funding_sells(ds, amount, exclude_sectors=None)
            orders, risk_notes = sells, risk_notes + notes
    else:
        warnings.append(f"Unknown action '{action}'.")

    return orders, funding_sources, risk_notes, warnings


def _orders_by_manual(ds, selections, amount):
    """Generate equal-value orders for securities explicitly selected by the user."""
    orders, funding_sources, risk_notes, warnings = [], [], [], []
    selected = []
    for selection in selections:
        ticker = selection.get("ticker")
        side = selection.get("side")
        if (ticker, side) not in selected and (data.universe_entry(ticker) or data.holding(ds, ticker)):
            selected.append((ticker, side))

    if not selected:
        return orders, funding_sources, risk_notes, ["Select at least one security for manual allocation."]

    for ticker, side in selected:
        selection_amount = next(
            item.get("amount_cr", 0.0) * CRORE for item in selections
            if item.get("ticker") == ticker and item.get("side") == side
        )
        if side == "BUY":
            order = _order(ds, ticker, "BUY", rupees=selection_amount)
            if order["shares"] > 0:
                orders.append(order)
            continue

        if side == "SELL":
            holding = data.holding(ds, ticker)
            if not holding:
                warnings.append(f"{ticker} is not held by this fund and was skipped for selling.")
                continue
            shares = int(min(selection_amount, holding["sellable_shares"] * holding["price"]) // holding["price"])
            if shares > 0:
                orders.append(_order(ds, ticker, "SELL", shares=shares))
            if holding["locked_shares"] > 0 and selection_amount > holding["sellable_shares"] * holding["price"]:
                risk_notes.append({"type": "lock_in", "severity": "MEDIUM", "ticker": ticker,
                                   "message": f"{ticker} sell capped by locked shares."})
    buy_total = sum(o["est_value"] for o in orders if o["side"] == "BUY")
    sell_total = sum(o["est_value"] for o in orders if o["side"] == "SELL")
    if buy_total:
        funding_sources.append({"ticker": "CASH", "name": "Available cash", "sector": "Cash",
                                "side": "USE", "shares": 0, "price": 0, "est_value": buy_total,
                                "reason": "Manual BUY selections."})
    if sell_total:
        funding_sources.append({"ticker": "MANUAL-SELL", "name": "Selected securities", "sector": "Cash",
                                "side": "OUT", "shares": 0, "price": 0, "est_value": sell_total,
                                "reason": "Manual SELL selections."})

    return orders, funding_sources, risk_notes, warnings


# --------------------------------------------------------------------------- #
# Order generation — convex optimization (forecast-driven, CVXPY)
# --------------------------------------------------------------------------- #
def _buy_candidates(ds, sectors, returns):
    """Buyable names: the fund's holdings plus the sector universe, restricted to
    `sectors` when given (for a sector-targeted increase)."""
    seen, out = set(), []
    for h in ds["holdings"]:
        if sectors and h["sector"] not in sectors:
            continue
        if not _usable_price(h["price"]):
            continue
        seen.add(h["ticker"])
        out.append({"ticker": h["ticker"], "price": h["price"], "sector": h["sector"],
                    "current_value": h["market_value"], "expected_return": returns.get(h["ticker"], 0.0)})
    for u in data.UNIVERSE:
        if u["ticker"] in seen:
            continue
        if policy.buy_exclusion_reason(ds, u["ticker"]) is not None:
            continue
        if sectors and u["sector"] not in sectors:
            continue
        held = data.holding(ds, u["ticker"])
        out.append({"ticker": u["ticker"], "price": u["price"], "sector": u["sector"],
                    "current_value": held["market_value"] if held else 0.0,
                    "expected_return": returns.get(u["ticker"], 0.0)})
    return out


def _sell_candidates(ds, sectors, returns):
    return [{"ticker": h["ticker"], "price": h["price"],
             "sellable_shares": _available_sellable_shares(ds, h),
             "expected_return": returns.get(h["ticker"], 0.0),
             # Exit tax (blended STCG/LTCG over the synthetic lots; negative for
             # loss positions) and transaction cost, per rupee of proceeds.
             "tax_rate": (h.get("effective_tax_rate_pct") or 0.0) / 100,
             "txn_rate": (h.get("txn_cost_rate_pct") or 0.0) / 100}
            for h in ds["holdings"]
            if (not sectors or h["sector"] in sectors)
            and _available_sellable_shares(ds, h) > 0
            and _usable_price(h["price"])]


def _historical_stock_context(ds):
    metrics_by_isin = db.get_stock_risk_return_metrics() or {}
    metrics_by_ticker = {
        metric["symbol"]: metric for metric in metrics_by_isin.values()
        if metric.get("symbol")
    }
    isin_by_ticker = {ticker: metric["isin"] for ticker, metric in metrics_by_ticker.items()}
    for holding in ds["holdings"]:
        if holding.get("isin"):
            isin_by_ticker[holding["ticker"]] = holding["isin"]
    return metrics_by_isin, metrics_by_ticker, isin_by_ticker


def _build_risk_context(ds, target_volatility):
    """Build a historical covariance matrix and the requested risk target.

    The covariance includes current holdings and every mapped buy-universe
    security, so new positions participate in target tracking instead of
    disappearing from the optimizer's risk calculation.
    """
    fund_metrics = db.get_fund_risk_return_metrics(ds["id"]) if ds["id"] in data_v2.FUNDS_V2 else None
    selected_target = target_volatility
    if selected_target is None and fund_metrics:
        selected_target = fund_metrics.get("strategy_volatility_high")
    if selected_target is None or selected_target < 0:
        return None

    metrics_by_isin, _, isin_by_ticker = _historical_stock_context(ds)
    candidate_tickers = list(dict.fromkeys(
        [h["ticker"] for h in ds["holdings"]]
        + [item["ticker"] for item in data.UNIVERSE]
    ))
    risk_tickers = [ticker for ticker in candidate_tickers if isin_by_ticker.get(ticker)]
    if len(risk_tickers) < 2:
        return None
    kept, cov_monthly, dropped = risk_model.build_covariance(risk_tickers, isin_by_ticker)
    stock_metrics = {
        isin: metrics_by_isin[isin] for isin in set(isin_by_ticker.values())
        if isin in metrics_by_isin
    }
    default_vol = (fund_metrics or {}).get("annualized_volatility") or 0.20
    all_tickers, cov_monthly = risk_model.extend_with_diagonal_fallback(
        kept, cov_monthly, dropped, isin_by_ticker, stock_metrics, default_vol,
    )
    if len(all_tickers) < 2:
        return None
    return {
        "tickers": all_tickers,
        "cov_monthly": cov_monthly,
        "target_volatility": float(selected_target),
        "sigma_max_annual": float(selected_target),
        "current_value_by_ticker": {h["ticker"]: h["market_value"] for h in ds["holdings"]},
        "dropped_tickers": dropped,
        "fund_metrics": fund_metrics,
    }


def _estimate_post_trade_risk_return(ds, orders, target_volatility, action, amount):
    """Estimate comparable before/after returns and risk from historical data."""
    fund_metrics = db.get_fund_risk_return_metrics(ds["id"]) if ds["id"] in data_v2.FUNDS_V2 else None
    selected_target = target_volatility
    if selected_target is None:
        selected_target = (fund_metrics or {}).get("strategy_volatility_high")

    current_value = {h["ticker"]: h["market_value"] for h in ds["holdings"]}
    delta = {}
    for o in orders:
        sign = 1 if o["side"] == "BUY" else -1
        delta[o["ticker"]] = delta.get(o["ticker"], 0.0) + sign * o["est_value"]
    post_value = dict(current_value)
    for ticker, d in delta.items():
        post_value[ticker] = post_value.get(ticker, 0.0) + d
    aum = ds["aum"] or 1.0
    post_aum = aum + amount if action == "contribution" else aum
    if action == "redemption":
        planned_redemption = sum(
            max(o.get("est_value", 0.0), 0.0) for o in orders if o.get("side") == "SELL"
        )
        post_aum = max(aum - planned_redemption, 1.0)

    metrics_by_isin, metrics_by_ticker, isin_by_ticker = _historical_stock_context(ds)
    all_tickers = list(dict.fromkeys(current_value.keys() | post_value.keys()))
    all_tickers = [ticker for ticker in all_tickers if isin_by_ticker.get(ticker)]
    kept, cov_monthly, dropped = risk_model.build_covariance(all_tickers, isin_by_ticker)
    stock_metrics = {
        isin: metrics_by_isin[isin] for isin in set(isin_by_ticker.values())
        if isin in metrics_by_isin
    }
    all_tickers, cov_monthly = risk_model.extend_with_diagonal_fallback(
        kept, cov_monthly, dropped, isin_by_ticker, stock_metrics,
        (fund_metrics or {}).get("annualized_volatility") or 0.20,
    )

    def historical_volatility(values, portfolio_aum):
        if len(all_tickers) < 2:
            return None
        weights = np.array([max(values.get(ticker, 0.0), 0.0) / portfolio_aum for ticker in all_tickers])
        return risk_model.portfolio_annual_volatility(weights, cov_monthly)

    def historical_return(values, portfolio_aum):
        return sum(
            max(value, 0.0) * (metrics_by_ticker.get(ticker, {}).get("annualized_return") or 0.0)
            for ticker, value in values.items()
        ) / portfolio_aum

    current_volatility = historical_volatility(current_value, aum)
    post_volatility = historical_volatility(post_value, post_aum)
    current_return = historical_return(current_value, aum)
    post_return = historical_return(post_value, post_aum)
    target_gap = post_volatility - selected_target if post_volatility is not None and selected_target is not None else None
    target_tolerance = max(0.002, (selected_target or 0.0) * 0.02)

    return {
        "fund_strategy_band": {
            "return_low": (fund_metrics or {}).get("strategy_return_low"),
            "return_high": (fund_metrics or {}).get("strategy_return_high"),
            "volatility_low": (fund_metrics or {}).get("strategy_volatility_low"),
            "volatility_high": (fund_metrics or {}).get("strategy_volatility_high"),
            "source": (fund_metrics or {}).get("strategy_range_source"),
        } if fund_metrics else None,
        "fund_current_annualized_return": round(current_return, 4),
        "fund_current_annualized_volatility": (
            round(current_volatility, 4) if current_volatility is not None else None),
        "target_volatility": selected_target,
        "estimated_post_trade_annualized_return": round(post_return, 4),
        "estimated_post_trade_annualized_volatility": (
            round(post_volatility, 4) if post_volatility is not None else None),
        "volatility_target_gap": round(target_gap, 4) if target_gap is not None else None,
        "volatility_target_reached": (
            abs(target_gap) <= target_tolerance if target_gap is not None else None),
        "historical_metric_coverage_pct": round(
            sum(max(value, 0.0) for ticker, value in post_value.items()
                if ticker in metrics_by_ticker) / post_aum * 100, 1),
        "covariance_coverage": len(all_tickers),
    }


def _orders_by_optimizer(ds, action, sectors, amount, investable, returns, horizon_days=None,
                         target_volatility=None):
    """Forecast-driven order generation. Returns the usual tuple plus an
    optimization-meta dict. Raises on solver problems so the caller can fall
    back to the rule-based path."""
    orders, funding_sources, risk_notes, warnings = [], [], [], []
    opt_meta = None
    aum = ds["aum"]
    risk_ctx = _build_risk_context(ds, target_volatility)

    if action in ("contribution", "increase", "buy", "add"):
        if action != "contribution" and not sectors:
            warnings.append(f"Could not map target to a known sector; no buy orders generated.")
            return orders, funding_sources, risk_notes, warnings, opt_meta
        candidates = _buy_candidates(ds, sectors if action != "contribution" else None, returns)
        # Respect the fund's own mandate caps as hard optimizer constraints, and
        # measure them against the post-trade AUM (a contribution grows AUM by
        # the deployed cash) so the optimizer never proposes a breaching book.
        lim = (data_v2.get_fund_compliance_limits(ds["id"])
               if ds["id"] in data_v2.FUNDS_V2 else data.COMPLIANCE_LIMITS)
        cap_aum = aum + amount if action == "contribution" else aum
        sector_current = {}
        for h in ds["holdings"]:
            sector_current[h["sector"]] = sector_current.get(h["sector"], 0.0) + h["market_value"]
        allocations, opt_meta = optimizer.optimize_buy(
            candidates, amount, aum, lim["single_issuer_limit"] / 100,
            sector_cap_frac=lim["sector_soft_limit"] / 100,
            sector_current=sector_current, cap_aum=cap_aum, risk=risk_ctx)
        for a in allocations:
            orders.append({**_order(ds, a["ticker"], "BUY", shares=a["shares"]),
                           "reason": "Convex-optimized to maximize forecast return"})
        buy_total = sum(o["est_value"] for o in orders)
        if action == "contribution":
            funding_sources = [{"ticker": "INFLOW", "name": "Contribution / subscription inflow",
                                "sector": "Cash", "side": "IN", "shares": 0, "price": 0,
                                "est_value": amount, "reason": "New cash deployed by convex optimizer to maximize forecast return."}]
        else:
            gap = buy_total - investable
            if gap > 0:
                sells, notes = _funding_sells(ds, gap, exclude_sectors=sectors or None)
                funding_sources, orders = sells, orders + sells
                risk_notes.extend(notes)
                warnings.append(f"Purchase exceeds investable cash by ~Rs {gap / CRORE:,.1f} Cr; funded by trimming holdings.")
            else:
                funding_sources = [{"ticker": "CASH", "name": "Available cash", "sector": "Cash",
                                    "side": "USE", "shares": 0, "price": 0, "est_value": buy_total,
                                    "reason": "Fully funded from investable cash."}]

    elif action in ("redemption", "decrease", "sell", "trim", "raise_cash"):
        sec = sectors if action in ("decrease", "sell", "trim") else None
        candidates = _sell_candidates(ds, sec, returns)
        sells, opt_meta = optimizer.optimize_sell(candidates, amount, horizon_days=horizon_days,
                                                   risk=risk_ctx, aum=aum)
        for sdict in sells:
            orders.append({**_order(ds, sdict["ticker"], "SELL", shares=sdict["shares"]),
                           "reason": "Convex-optimized to minimize forecast return given up + exit tax"})
        raised = sum(o["est_value"] for o in orders if o["side"] == "SELL")
        if action == "redemption":
            funding_sources = [{"ticker": "OUTFLOW", "name": "Redemption / payout", "sector": "Cash",
                                "side": "OUT", "shares": 0, "price": 0, "est_value": raised,
                                "reason": "Cash raised by selling the lowest-forecast-return names."}]

    elif action == "rebalance":
        existing_by_ticker = {h["ticker"]: h for h in ds["holdings"]}
        holdings = [
            {**h, "sellable_shares": _available_sellable_shares(ds, h),
             "expected_return": returns.get(h["ticker"], 0.0)}
            for h in ds["holdings"]
        ]
        for candidate in _buy_candidates(ds, None, returns):
            if candidate["ticker"] in existing_by_ticker:
                continue
            holdings.append({
                "ticker": candidate["ticker"], "price": candidate["price"],
                "market_value": 0.0, "sellable_shares": 0,
                "expected_return": candidate["expected_return"],
                "effective_tax_rate_pct": 0.0, "txn_cost_rate_pct": 0.0,
            })
        targets, opt_meta = optimizer.optimize_rebalance(holdings, aum, _ISSUER_CAP_FRAC, risk=risk_ctx)
        min_ticket = 0.25 * CRORE
        rebalance_by_ticker = {h["ticker"]: h for h in holdings}
        for t in targets:
            ticker = t["ticker"]
            h = existing_by_ticker.get(ticker)
            candidate = rebalance_by_ticker[ticker]
            delta = t["delta_rupees"]
            if abs(delta) < min_ticket or not _usable_price(candidate["price"]):
                continue
            if delta > 0:
                shares = int(delta // candidate["price"])
                if shares > 0:
                    orders.append({**_order(ds, ticker, "BUY", shares=shares),
                                   "reason": "Convex rebalance toward higher forecast return"})
            elif h:
                sellable_value = _available_sellable_shares(ds, h) * h["price"]
                shares = int(min(-delta, sellable_value) // h["price"])
                if shares > 0:
                    orders.append({**_order(ds, ticker, "SELL", shares=shares),
                                   "reason": "Convex rebalance toward higher forecast return"})
    else:
        warnings.append(f"Unknown action '{action}'.")

    return orders, funding_sources, risk_notes, warnings, opt_meta


# --------------------------------------------------------------------------- #
# Tax context for the policy layer
# --------------------------------------------------------------------------- #
_SELL_ACTIONS = ("redemption", "decrease", "sell", "trim", "raise_cash", "rebalance")


def _tax_context(ds, orders, returns, action, horizon_days, as_of, ltcg_exemption_used_this_fy=0.0):
    """Plan-level tax facts for policy: totals per term, and any predicted
    loser that was kept only because its exit tax exceeded the expected loss
    (tax is one-time; a predicted loss repeats)."""
    total_tax = stcg_value = ltcg_gain_total = 0.0
    for o in orders:
        t = o.get("tax")
        if not t:
            continue
        total_tax += t["total_tax"]
        ltcg_gain_total += t["ltcg_gain"]
        stcg_value += sum(l["shares"] for l in t["lots_consumed"]
                          if l["term"] == "STCG") * o["price"]
    # Annual Rs 1.25 lakh LTCG exemption is a once-a-year allowance, not a
    # once-a-plan one — net off whatever this fund's approved+sent plans
    # already used so far this financial year before applying what's left.
    exemption_remaining = max(tax_rules.LTCG_EXEMPTION_INR - ltcg_exemption_used_this_fy, 0.0)
    exemption_used = min(max(ltcg_gain_total, 0.0), exemption_remaining)
    exemption_relief = exemption_used * tax_rules.LTCG_RATE
    total_tax = total_tax - exemption_relief
    sell_value = sum(o["est_value"] for o in orders if o["side"] == "SELL")

    held_due_to_tax = []
    if action in _SELL_ACTIONS:
        sold = {o["ticker"] for o in orders if o["side"] == "SELL"}
        horizon_scale = max(horizon_days, 1) / 21.0
        for h in ds["holdings"]:
            r = returns.get(h["ticker"], 0.0)
            if r >= 0 or h["ticker"] in sold or not h.get("tax_lots"):
                continue
            exit_rate = ((h.get("effective_tax_rate_pct") or 0.0)
                         + (h.get("txn_cost_rate_pct") or 0.0)) / 100
            if exit_rate <= 0 or exit_rate <= abs(r) * horizon_scale:
                continue
            stcg_maturities = [
                tax_rules.ltcg_date(date.fromisoformat(l["acquisition_date"]))
                for l in h["tax_lots"]
                if tax_rules.classify_term(date.fromisoformat(l["acquisition_date"]), as_of) == "STCG"
            ]
            held_due_to_tax.append({
                "ticker": h["ticker"],
                "expected_return_pct": round(r * 100, 3),
                "exit_cost_pct": round(exit_rate * 100, 3),
                "ltcg_maturity": min(stcg_maturities).isoformat() if stcg_maturities else None,
            })

    return {
        "est_total_tax": round(total_tax, 2),
        "ltcg_exemption_relief": round(exemption_relief, 2),
        "ltcg_exemption_used_inr": round(exemption_used, 2),
        "ltcg_exemption_remaining_inr": round(exemption_remaining - exemption_used, 2),
        "sell_value": sell_value,
        "tax_drag_bps": round(total_tax / sell_value * 10_000, 1) if sell_value else 0.0,
        "stcg_share_pct": round(stcg_value / sell_value * 100, 1) if sell_value else 0.0,
        "held_due_to_tax": held_due_to_tax,
    }


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #
def _cr(amount):
    """Rupees -> crore, rounded for display in progress details."""
    return round((amount or 0) / CRORE, 2)


def _step(phase, phase_index, step, label, detail, data=None):
    """Build one granular progress event belonging to a phase."""
    return {
        "type": "progress", "phase": phase, "index": phase_index, "total": 5,
        "step": step, "label": label, "detail": detail, "data": data or {},
    }


def generate_plan(fund_id, intent):
    """Build a plan and return the final dict.

    Thin wrapper that drains :func:`iter_plan_steps` for callers that only need
    the finished plan (the plain POST endpoint and the test matrix).
    """
    plan = None
    for event in iter_plan_steps(fund_id, intent):
        if event.get("type") == "plan":
            plan = event["plan"]
    return plan


def iter_plan_steps(fund_id, intent):
    """Generate a plan, yielding real progress events at each phase boundary.

    Yields ``{"type": "progress", ...}`` dicts as each phase actually completes
    (carrying real computed values, not canned text) and finally a single
    ``{"type": "plan", "plan": <plan dict>}``. The SSE endpoint streams these;
    :func:`generate_plan` drains them for non-streaming callers.
    """
    # _get_ds returns the SAME cached dict every call (data_v2.FUNDS_V2[...] /
    # data.FUNDS[...]) — shallow-copy it before attaching request-scoped data so
    # we never mutate the shared cache (a prior version assigned directly into
    # the cached dict's "pending_trades" key, which permanently baked that
    # moment's approved-plan trades into the shared cache and caused them to be
    # re-added — duplicated — on every later read).
    ds = dict(_get_ds(fund_id))
    # Augment static pending trades with orders from approved plans so this plan
    # sees the full commitment picture (reduced investable cash, reduced
    # sellable shares, etc.). This is part of cross-plan awareness.
    ds["pending_trades"] = (
        list(ds["pending_trades"]) +
        _augment_pending_trades_from_approved_plans(fund_id)
    )
    as_of = date.today()
    # Tax lots are reattached fresh from the synthetic universe on every plan,
    # so without this a lot an approved+sent plan already sold would still
    # show up as available and get "sold" again by a later plan. Copy the
    # holdings (same shared-cache-mutation hazard as pending_trades above)
    # before trimming any already-consumed lot quantities.
    consumed_lots = _consumed_tax_lots_by_ticker(fund_id)
    if consumed_lots:
        ds["holdings"] = [dict(h) for h in ds["holdings"]]
        for h in ds["holdings"]:
            by_lot = consumed_lots.get(h["ticker"])
            if by_lot:
                tax_lots.apply_consumed_lots(h, by_lot, as_of)
        # holdings_by_ticker is a separate index built from the old (cached)
        # holding dicts — rebuild it from the copies so every lookup by
        # ticker (data.holding(), policy.py weight checks, etc.) sees the
        # adjusted tax lots too.
        ds["holdings_by_ticker"] = {h["ticker"]: h for h in ds["holdings"]}
    action = (intent.get("action") or "contribution").lower()
    target = intent.get("target") or ""
    amount = float(intent.get("amount_cr") or 0) * CRORE
    trade_date = intent.get("trade_date")
    settlement_date = intent.get("settlement_date")
    horizon = ((settlement_date - trade_date).days
               if trade_date and settlement_date
               else int(intent.get("horizon_days") or 5))
    trade_date = trade_date.isoformat() if isinstance(trade_date, date) else trade_date
    settlement_date = (settlement_date.isoformat()
                       if isinstance(settlement_date, date) else settlement_date)

    # Resolve one or more target sectors. `targets` (list) takes precedence; a
    # single `target` (optionally comma-separated) is still accepted.
    raw_targets = intent.get("targets")
    if not raw_targets:
        raw_targets = [t for t in target.split(",")] if target else []
    sectors = []
    for t in raw_targets:
        s = resolve_sector(t)
        if s and s not in sectors:
            sectors.append(s)
    yield _step("intent", 0, "intent:parse", "Parsed portfolio manager intent",
                f"Action {action} · ₹{intent.get('amount_cr') or 0} cr · "
                f"method {(intent.get('method') or 'optimize')}",
                {"action": action, "amount_cr": intent.get("amount_cr"),
                 "method": intent.get("method") or "optimize"})
    yield _step("intent", 0, "intent:sectors", "Resolved target sectors",
                (", ".join(sectors) if sectors else "Portfolio-level — no sector target"),
                {"resolved_sectors": sectors})
    yield _step("intent", 0, "intent:horizon", "Checked settlement horizon",
                f"{horizon} day(s) trade → settlement",
                {"horizon_days": horizon, "trade_date": trade_date,
                 "settlement_date": settlement_date})
    cfp = cash_flow_planning(ds, horizon)
    # A contribution brings new subscription cash into the fund. Reflect it in
    # the investable balance so the plan can deploy it and the cash-deployment
    # policy check measures against the money that actually arrived.
    if action == "contribution" and amount > 0:
        cfp["subscription_amount"] = amount
        cfp["investable_amount"] = cfp["investable_amount"] + amount
        cfp["line_items"].append({"label": "New subscription (this plan)", "amount": amount})
    investable = cfp["investable_amount"]
    yield _step("cash_flow", 1, "cash_flow:onhand", "Loaded cash and reserve buffer",
                f"Cash ₹{_cr(cfp['total_cash'])} cr · reserves ₹{_cr(cfp['reserves'])} cr",
                {"total_cash_cr": _cr(cfp["total_cash"]), "reserves_cr": _cr(cfp["reserves"])})
    yield _step("cash_flow", 1, "cash_flow:flows", "Applied pending flows and dividends",
                f"Pending net ₹{_cr(cfp['pending_settlement_net'])} cr · "
                f"dividends ₹{_cr(cfp['expected_dividends'])} cr",
                {"pending_net_cr": _cr(cfp["pending_settlement_net"]),
                 "dividends_cr": _cr(cfp["expected_dividends"])})
    yield _step("cash_flow", 1, "cash_flow:expenses", "Deducted accrued expenses and net flows",
                f"Expenses ₹{_cr(cfp['expected_expenses'])} cr · "
                f"net sub/red ₹{_cr(cfp['estimated_subscriptions'] + cfp['estimated_redemptions'])} cr",
                {"expenses_cr": _cr(cfp["expected_expenses"])})
    yield _step("cash_flow", 1, "cash_flow:investable", "Calculated investable cash",
                f"Investable ₹{_cr(investable)} cr",
                {"investable_cr": _cr(investable), "line_items": cfp.get("line_items")})

    # Forecast expected 1-month returns (TFT placeholder). Used by the convex
    # optimizer and shown in the plan regardless of method.
    returns = forecast.predict_returns(
        [h["ticker"] for h in ds["holdings"]] + [u["ticker"] for u in data.UNIVERSE]
    )

    # Allocation method: "manual", "rules" (heuristics) or "optimize" (forecast-driven
    # convex optimization). Optimize falls back to rules on any problem so a plan
    # is always produced; the compliance & risk *rules* run on the result either
    # way.
    requested_method = (intent.get("method") or "optimize").lower()
    method_used = requested_method
    opt_meta = None

    if requested_method == "manual":
        manual_selections = intent.get("manual_selections") or []
        manual_sector_selections = intent.get("manual_sector_selections") or []
        if manual_sector_selections:
            manual_side = "BUY" if action == "increase" else "SELL"
            for sector_selection in manual_sector_selections:
                sector_names = [
                    item for item in (data.UNIVERSE if action == "increase" else ds["holdings"])
                    if item["sector"] == sector_selection["sector"]
                ]
                per_security_cr = sector_selection["amount_cr"] / len(sector_names) if sector_names else 0
                manual_selections.extend([
                    {"ticker": item["ticker"], "side": manual_side, "amount_cr": per_security_cr}
                    for item in sector_names
                ])
        if not manual_selections and action in ("increase", "decrease"):
            manual_side = "BUY" if action == "increase" else "SELL"
            eligible = [
                candidate for candidate in (data.UNIVERSE if action == "increase" else ds["holdings"])
                if not sectors or candidate["sector"] in sectors
            ]
            per_security_cr = amount / CRORE / len(eligible) if eligible else 0
            manual_selections = [
                {"ticker": item["ticker"], "side": manual_side, "amount_cr": per_security_cr}
                for item in eligible
            ]
        orders, funding_sources, risk_notes, warnings = _orders_by_manual(
            ds, manual_selections, amount)
    elif requested_method == "optimize":
        if not optimizer.available():
            method_used = "rules"
            orders, funding_sources, risk_notes, warnings = _orders_by_rules(
                ds, action, sectors, amount, investable, target)
            warnings.append(f"Convex optimizer unavailable ({optimizer.import_error()}); "
                            "used rule-based allocation. Install backend requirements (cvxpy) to enable it.")
        else:
            try:
                orders, funding_sources, risk_notes, warnings, opt_meta = _orders_by_optimizer(
                    ds, action, sectors, amount, investable, returns, horizon,
                    target_volatility=intent.get("target_volatility"))
            except Exception as exc:  # solver / feasibility issue -> fall back
                method_used = "rules"
                orders, funding_sources, risk_notes, warnings = _orders_by_rules(
                    ds, action, sectors, amount, investable, target)
                warnings.append(f"Convex optimization failed ({exc}); fell back to rule-based allocation.")
    else:
        orders, funding_sources, risk_notes, warnings = _orders_by_rules(
            ds, action, sectors, amount, investable, target)

    if trade_date and settlement_date:
        warnings.extend(_check_settlement_window(
            date.fromisoformat(trade_date), date.fromisoformat(settlement_date)))

    if trade_date and settlement_date and horizon > 0:
        warnings.extend(_schedule_order_trade_dates(
            ds, orders, returns, date.fromisoformat(trade_date), date.fromisoformat(settlement_date)))
    elif trade_date:
        for order in orders:
            order["trade_date"] = trade_date

    # Annotate every order with its forecast expected 1-month return.
    for o in orders:
        o["expected_return"] = round(returns.get(o["ticker"], forecast.expected_return(o["ticker"])), 4)
        if settlement_date:
            o["settlement_date"] = settlement_date

    buy_ct = sum(1 for o in orders if o["side"] == "BUY")
    sell_ct = sum(1 for o in orders if o["side"] == "SELL")
    yield _step("allocation", 2, "allocation:forecast", "Generated 1-month return forecasts",
                f"{len(returns)} tickers forecast",
                {"forecast_count": len(returns)})
    yield _step("allocation", 2, "allocation:method", "Ran the allocation engine",
                (f"{method_used}" + (f" · solver {opt_meta['solver']} ({opt_meta['status']})"
                                     if opt_meta else "")),
                {"method": method_used, "optimization": opt_meta})
    yield _step("allocation", 2, "allocation:orders", "Sized share-level orders",
                f"{len(orders)} order(s) · {buy_ct} buy / {sell_ct} sell",
                {"order_count": len(orders), "buy_count": buy_ct, "sell_count": sell_ct})
    _scheduled_ct = sum(1 for o in orders if o.get("trade_date"))
    _impact_so_far = sum(o.get("est_impact_cost") or 0 for o in orders)
    yield _step("allocation", 2, "allocation:schedule", "Scheduled order trade dates",
                (f"{_scheduled_ct}/{len(orders)} order(s) dated across trading sessions · "
                 f"~₹{_cr(_impact_so_far)} cr est. market-impact cost"
                 if _scheduled_ct else "No trade/settlement window supplied — dates not scheduled"),
                {"scheduled_count": _scheduled_ct, "est_impact_cost_cr": _cr(_impact_so_far)})

    # Attach the per-order tax breakdown (STCG/LTCG/STT over the synthetic
    # lots, consumed least-tax-first) to every SELL, whatever the method.
    for o in orders:
        if o["side"] != "SELL":
            continue
        h = data.holding(ds, o["ticker"])
        if h and h.get("tax_lots"):
            # Use the holding's real price for gains: `_order` prefers the
            # synthetic universe price for the 14 universe tickers, which
            # would distort gain/loss vs the real-history cost bases.
            sale_price = h["price"] if _usable_price(h.get("price")) else o["price"]
            breakdown = tax_lots.sale_tax_breakdown(h, sale_price, o["shares"], as_of)
            if breakdown:
                o["tax"] = breakdown

    # Attach STT/stamp-duty/brokerage friction to every BUY (no CGT on a buy,
    # but the transaction costs are real regardless of side).
    for o in orders:
        if o["side"] == "BUY" and o["est_value"] > 0:
            o["txn_cost"] = tax_rules.buy_txn_cost(o["est_value"])

    ltcg_exemption_used_this_fy = _ltcg_exemption_used_this_fy(fund_id, as_of)
    tax_context = _tax_context(ds, orders, returns, action, horizon, as_of,
                               ltcg_exemption_used_this_fy)
    buy_txn_cost_total = sum(o["txn_cost"]["total_cost"] for o in orders if o.get("txn_cost"))

    compliance = _compliance_checks(ds, orders, sectors)
    risks = _risk_flags(ds, orders, risk_notes, horizon)
    policy_result = policy.evaluate(ds, orders, cfp, horizon, tax_context=tax_context)
    risks.extend(policy_result["risk_flags"])
    warnings.extend(policy_result["warnings"])
    redemption_requested = amount if action == "redemption" else 0.0
    redemption_planned = sum(
        max(o.get("est_value", 0.0), 0.0) for o in orders if action == "redemption" and o.get("side") == "SELL"
    )
    redemption_shortfall = max(redemption_requested - redemption_planned, 0.0)
    shortfall_threshold = max(1_000_000.0, redemption_requested * 0.001)
    if action == "redemption" and redemption_shortfall > shortfall_threshold:
        shortfall_message = (
            f"Redemption shortfall: requested ₹{_cr(redemption_requested):,.2f} Cr, "
            f"planned sell orders raise ₹{_cr(redemption_planned):,.2f} Cr; "
            f"₹{_cr(redemption_shortfall):,.2f} Cr remains unfulfilled."
        )
        warnings.append(shortfall_message)
        risks.append({"type": "redemption_shortfall", "severity": "HIGH",
                      "message": shortfall_message})
    _fail_ct = sum(1 for c in compliance if c["status"] == "FAIL")
    _warn_ct = sum(1 for c in compliance if c["status"] == "WARN")
    _high_risk_ct = sum(1 for r in risks if r.get("severity") == "HIGH")
    yield _step("compliance_risk", 3, "compliance_risk:tax", "Calculated tax lots and drag",
                f"Est. tax ₹{_cr(tax_context['est_total_tax'])} cr · "
                f"drag {tax_context['tax_drag_bps']} bps",
                {"est_total_tax_cr": _cr(tax_context["est_total_tax"]),
                 "tax_drag_bps": tax_context["tax_drag_bps"]})
    yield _step("compliance_risk", 3, "compliance_risk:concentration",
                "Reprojected concentration limits",
                f"{len(compliance)} check(s) · {_fail_ct} fail · {_warn_ct} warn",
                {"compliance_fail": _fail_ct, "compliance_warn": _warn_ct,
                 "checks": compliance})
    yield _step("compliance_risk", 3, "compliance_risk:policy",
                "Evaluated liquidity, lock-ins, and policy",
                f"{_high_risk_ct} high-risk flag(s) · policy {policy_result['status']}",
                {"high_risk_flags": _high_risk_ct, "policy_status": policy_result["status"]})

    total_buy = sum(o["est_value"] for o in orders if o["side"] == "BUY")
    total_sell = sum(o["est_value"] for o in orders if o["side"] == "SELL")
    net_cash = total_sell - total_buy
    # net_cash above is gross of trading cost: sell proceeds haven't been
    # reduced by the exit tax actually paid on them, and buy value hasn't
    # been grossed up by the STT/stamp duty actually owed on it. This is the
    # reconciled figure - what cash the fund is actually left with once both
    # sides' tax/transaction costs are paid.
    net_cash_after_tax = net_cash - tax_context["est_total_tax"] - buy_txn_cost_total
    # Surfaced on cfp (not as a line_item - it's a post-trade reconciliation,
    # not one of the pre-trade cash-position components the other line_items
    # sum to) so the Cash-Flow Planning panel can show pre- and post-trade
    # cash side by side.
    cfp["net_cash_after_tax"] = round(net_cash_after_tax, 2)
    # Value-weighted estimated market-impact cost/bps across all scheduled
    # orders (0 for any order that wasn't date-scheduled, e.g. no trade/
    # settlement window was supplied).
    total_impact_cost = sum(o.get("est_impact_cost") or 0 for o in orders)
    total_order_value = sum(o["est_value"] for o in orders) or 1
    weighted_impact_bps = round(
        sum((o.get("est_impact_bps") or 0) * o["est_value"] for o in orders) / total_order_value, 1
    )

    has_fail = any(c["status"] == "FAIL" for c in compliance)
    has_policy_block = policy_result["status"] == "BLOCK"
    has_policy_escalation = policy_result["status"] == "ESCALATE"
    has_warn = (any(c["status"] == "WARN" for c in compliance)
                or any(r["severity"] == "HIGH" for r in risks)
                or policy_result["status"] == "WARN")
    if has_fail or has_policy_block:
        recommendation = "Plan is blocked by one or more policy or compliance limits. Recommend MODIFY or ESCALATE before execution."
    elif has_policy_escalation:
        recommendation = "Plan requires Compliance/PIC escalation because mandatory policy data or review is incomplete."
    elif has_warn:
        recommendation = "Plan is executable but has items near limits / elevated execution risk. Recommend REVIEW carefully, then APPROVE with monitoring."
    else:
        recommendation = "Plan is within all limits with low execution risk. Recommend APPROVE for execution."

    # Pending trades that affect this plan's cash picture (shown for full context).
    pending = [{**t, "gross_value_cr": round(t["gross_value"] / CRORE, 2),
                "cash_impact_cr": round(t["cash_impact"] / CRORE, 2)} for t in ds["pending_trades"]]

    risk_return = _estimate_post_trade_risk_return(
        ds, orders, intent.get("target_volatility"), action, amount)

    plan = {
        "plan_id": f"PLAN-{uuid.uuid4().hex[:8].upper()}",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "fund": {"fund_id": ds["id"], "name": ds["fund"]["name"], "aum_cr": round(ds["aum"] / CRORE, 2)},
        "intent": {"action": action, "target": target, "targets": raw_targets,
                   "resolved_sector": sectors[0] if len(sectors) == 1 else None,
                   "resolved_sectors": sectors,
                   "amount_cr": intent.get("amount_cr"), "horizon_days": horizon,
                   "trade_date": trade_date, "settlement_date": settlement_date,
                   "note": intent.get("note"),
                   "method": requested_method},
        "allocation_method": method_used,
        "optimization": opt_meta,
        "risk_return": risk_return,
        "forecast": forecast.summary(ds),
        "cash_flow_planning": cfp,
        "pending_trades": pending,
        "pending_net_cr": round(sum(t["cash_impact"] for t in ds["pending_trades"]) / CRORE, 2),
        "funding_sources": funding_sources,
        "orders": orders,
        "compliance_checks": compliance,
        "risk_flags": risks,
        "summary": {
            "order_count": len(orders), "total_buy_value": total_buy,
            "total_sell_value": total_sell, "net_cash_impact": net_cash,
            "net_cash_after_tax": round(net_cash_after_tax, 2),
            "net_cash_after_tax_cr": round(net_cash_after_tax / CRORE, 4),
            "investable_amount": investable,
            "redemption_requested_cr": round(redemption_requested / CRORE, 2) if action == "redemption" else None,
            "redemption_planned_cr": round(redemption_planned / CRORE, 2) if action == "redemption" else None,
            "redemption_shortfall_cr": round(redemption_shortfall / CRORE, 2) if action == "redemption" else None,
            "est_total_tax": tax_context["est_total_tax"],
            "est_total_tax_cr": round(tax_context["est_total_tax"] / CRORE, 4),
            "tax_drag_bps": tax_context["tax_drag_bps"],
            "stcg_share_pct": tax_context["stcg_share_pct"],
            "est_total_buy_cost": round(buy_txn_cost_total, 2),
            "est_total_buy_cost_cr": round(buy_txn_cost_total / CRORE, 4),
            "est_total_impact_cost": round(total_impact_cost, 0),
            "est_total_impact_cost_cr": round(total_impact_cost / CRORE, 4),
            "est_weighted_impact_bps": weighted_impact_bps,
            "compliance_status": "FAIL" if has_fail else ("WARN" if has_warn else "PASS"),
            "policy_status": policy_result["status"],
            "execution_allowed": policy_result["execution_allowed"] and not has_fail,
        },
        "tax_summary": {
            **tax_context,
            "buy_txn_cost_total": round(buy_txn_cost_total, 2),
            "rates": tax_rules.RATES,
            "note": ("Synthetic PMS-style capital-gains layer + real STT/charges. "
                     "Actual Indian mutual funds are CGT-exempt at fund level "
                     "(Section 10(23D)); see docs/taxation-model.md."),
        },
        "policy_checks": policy_result["checks"],
        "policy_summary": policy_result["summary"],
        "policy_version": policy_result["policy_version"],
        "policy_status": policy_result["status"],
        "execution_allowed": policy_result["execution_allowed"] and not has_fail,
        "warnings": warnings, "recommendation": recommendation, "status": "Pending PIC Review",
    }
    yield _step("package", 4, "package:cash", "Compiled net cash impact",
                f"Net cash ₹{_cr(net_cash)} cr · {plan['summary']['order_count']} order(s)",
                {"net_cash_cr": _cr(net_cash)})
    yield _step("package", 4, "package:recommendation", "Selected the recommendation",
                f"{plan['summary']['compliance_status']} · {recommendation.split('.')[0]}",
                {"compliance_status": plan["summary"]["compliance_status"],
                 "recommendation": recommendation})
    yield _step("package", 4, "package:created", "Created plan for PIC review",
                f"{plan['plan_id']} · {plan['status']}",
                {"plan_id": plan["plan_id"], "status": plan["status"]})
    yield {"type": "plan", "plan": plan}
