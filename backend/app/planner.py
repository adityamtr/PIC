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

import pandas_market_calendars as mcal

from . import data, data_v2, forecast, optimizer, policy, tax_lots, tax_rules

CRORE = data.CRORE

# Per-issuer cap (fraction of AUM) the convex optimizer respects up-front, so its
# proposals arrive already inside the SEBI single-issuer limit that the
# compliance rules re-check afterwards.
_ISSUER_CAP_FRAC = data.COMPLIANCE_LIMITS["single_issuer_limit"] / 100

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
    price = _price_for(ds, ticker)
    if shares is None:
        shares = int(rupees // price) if price else 0
    return {
        "ticker": ticker, "name": _name_for(ds, ticker), "sector": _sector_for(ds, ticker),
        "side": side, "shares": shares, "price": price, "est_value": shares * price,
    }


def _schedule_order_trade_dates(ds, orders, trade_date, settlement_date):
    """Suggest regular-session dates, balancing orders by estimated ADV impact."""
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

    def liquidity_load(order):
        entity = policy._entity(ds, order["ticker"])
        adv_cr = entity.get("adv_cr")
        median_adv_cr = entity.get("median_adv_cr") or adv_cr
        effective_adv_cr = min(adv_cr, median_adv_cr) if adv_cr and median_adv_cr else None
        value_cr = float(order.get("est_value") or 0) / CRORE
        return value_cr / effective_adv_cr if effective_adv_cr else value_cr

    ordered = sorted(
        orders,
        key=lambda order: (
            order.get("side") != "SELL",
            -liquidity_load(order),
            order.get("ticker", ""),
        ),
    )
    daily_load = {day: 0.0 for day in trading_dates}
    for order in ordered:
        selected_date = min(trading_dates, key=lambda day: (daily_load[day], day))
        order["trade_date"] = selected_date.isoformat()
        daily_load[selected_date] += liquidity_load(order)

    return []


def _usable_price(price):
    return isinstance(price, (int, float)) and math.isfinite(price) and price > 0


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


def _orders_by_optimizer(ds, action, sectors, amount, investable, returns, horizon_days=None):
    """Forecast-driven order generation. Returns the usual tuple plus an
    optimization-meta dict. Raises on solver problems so the caller can fall
    back to the rule-based path."""
    orders, funding_sources, risk_notes, warnings = [], [], [], []
    opt_meta = None
    aum = ds["aum"]

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
            sector_current=sector_current, cap_aum=cap_aum)
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
        sells, opt_meta = optimizer.optimize_sell(candidates, amount, horizon_days=horizon_days)
        for sdict in sells:
            orders.append({**_order(ds, sdict["ticker"], "SELL", shares=sdict["shares"]),
                           "reason": "Convex-optimized to minimize forecast return given up + exit tax"})
        raised = sum(o["est_value"] for o in orders if o["side"] == "SELL")
        if action == "redemption":
            funding_sources = [{"ticker": "OUTFLOW", "name": "Redemption / payout", "sector": "Cash",
                                "side": "OUT", "shares": 0, "price": 0, "est_value": raised,
                                "reason": "Cash raised by selling the lowest-forecast-return names."}]

    elif action == "rebalance":
        holdings = [{**h, "expected_return": returns.get(h["ticker"], 0.0)} for h in ds["holdings"]]
        targets, opt_meta = optimizer.optimize_rebalance(holdings, aum, _ISSUER_CAP_FRAC)
        min_ticket = 0.25 * CRORE
        for t in targets:
            h = data.holding(ds, t["ticker"])
            delta = t["delta_rupees"]
            if abs(delta) < min_ticket or not h or not _usable_price(h["price"]):
                continue
            if delta > 0:
                shares = int(delta // h["price"])
                if shares > 0:
                    orders.append({**_order(ds, h["ticker"], "BUY", shares=shares),
                                   "reason": "Convex rebalance toward higher forecast return"})
            else:
                sellable_value = h["sellable_shares"] * h["price"]
                shares = int(min(-delta, sellable_value) // h["price"])
                if shares > 0:
                    orders.append({**_order(ds, h["ticker"], "SELL", shares=shares),
                                   "reason": "Convex rebalance toward higher forecast return"})
    else:
        warnings.append(f"Unknown action '{action}'.")

    return orders, funding_sources, risk_notes, warnings, opt_meta


# --------------------------------------------------------------------------- #
# Tax context for the policy layer
# --------------------------------------------------------------------------- #
_SELL_ACTIONS = ("redemption", "decrease", "sell", "trim", "raise_cash", "rebalance")


def _tax_context(ds, orders, returns, action, horizon_days, as_of):
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
    # Annual Rs 1.25 lakh LTCG exemption, applied once at plan level (it is
    # negligible at crore scale but kept for correctness).
    exemption_relief = min(max(ltcg_gain_total, 0.0),
                           tax_rules.LTCG_EXEMPTION_INR) * tax_rules.LTCG_RATE
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
    ds = _get_ds(fund_id)
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
                    ds, action, sectors, amount, investable, returns, horizon)
            except Exception as exc:  # solver / feasibility issue -> fall back
                method_used = "rules"
                orders, funding_sources, risk_notes, warnings = _orders_by_rules(
                    ds, action, sectors, amount, investable, target)
                warnings.append(f"Convex optimization failed ({exc}); fell back to rule-based allocation.")
    else:
        orders, funding_sources, risk_notes, warnings = _orders_by_rules(
            ds, action, sectors, amount, investable, target)

    if trade_date and settlement_date and horizon > 0:
        warnings.extend(_schedule_order_trade_dates(
            ds, orders, date.fromisoformat(trade_date), date.fromisoformat(settlement_date)))
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

    # Attach the per-order tax breakdown (STCG/LTCG/STT over the synthetic
    # lots, consumed least-tax-first) to every SELL, whatever the method.
    as_of = date.today()
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

    tax_context = _tax_context(ds, orders, returns, action, horizon, as_of)

    compliance = _compliance_checks(ds, orders, sectors)
    risks = _risk_flags(ds, orders, risk_notes, horizon)
    policy_result = policy.evaluate(ds, orders, cfp, horizon, tax_context=tax_context)
    risks.extend(policy_result["risk_flags"])
    warnings.extend(policy_result["warnings"])
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
            "investable_amount": investable,
            "est_total_tax": tax_context["est_total_tax"],
            "est_total_tax_cr": round(tax_context["est_total_tax"] / CRORE, 4),
            "tax_drag_bps": tax_context["tax_drag_bps"],
            "stcg_share_pct": tax_context["stcg_share_pct"],
            "compliance_status": "FAIL" if has_fail else ("WARN" if has_warn else "PASS"),
            "policy_status": policy_result["status"],
            "execution_allowed": policy_result["execution_allowed"] and not has_fail,
        },
        "tax_summary": {
            **tax_context,
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
