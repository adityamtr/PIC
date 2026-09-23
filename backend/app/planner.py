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

import uuid
from datetime import datetime, timezone

from . import data, forecast, optimizer

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


# --------------------------------------------------------------------------- #
# 1. Cash-flow planning
# --------------------------------------------------------------------------- #
def cash_flow_planning(ds, horizon_days):
    total_cash = ds["cash"]["total_cash"]
    reserves = ds["cash"]["reserves"]
    pending_net = sum(t["cash_impact"] for t in ds["pending_trades"])
    dividends = sum(ca["cash_amount"] for ca in ds["corporate_actions"]
                    if ca["pay_offset_days"] <= horizon_days)
    expenses = ds["fund_expense"]["daily_accrual"] * horizon_days
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
        for ticker, frac in alloc.items():
            o = _order(ds, ticker, "BUY", rupees=amount * frac)
            if o["shares"] > 0:
                orders.append(o)
    else:
        names = [h for h in ds["holdings"] if h["sector"] == sector]
        total_w = sum(h["weight"] for h in names) or 1.0
        for h in names:
            o = _order(ds, h["ticker"], "BUY", rupees=amount * h["weight"] / total_w)
            if o["shares"] > 0:
                orders.append(o)
    return orders


def _funding_sells(ds, gap, exclude_sectors=None):
    exclude = set(exclude_sectors or [])
    candidates = sorted((h for h in ds["holdings"] if h["sector"] not in exclude),
                        key=lambda h: h["weight"])
    sources, notes, remaining = [], [], gap
    for h in candidates:
        if remaining <= 0:
            break
        sellable_value = h["sellable_shares"] * h["price"]
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

    shortfalls = [(h, (h["target_weight"] - h["weight"]) / 100 * aum)
                  for h in ds["holdings"] if h["weight"] < h["target_weight"]]
    total_short = sum(s for _, s in shortfalls)
    fill = min(amount, total_short)
    if total_short > 0:
        for h, short in shortfalls:
            rupees[h["ticker"]] += fill * short / total_short

    remaining = amount - fill
    if remaining > 1:
        tw_total = sum(h["target_weight"] for h in ds["holdings"]) or 1.0
        for h in ds["holdings"]:
            rupees[h["ticker"]] += remaining * h["target_weight"] / tw_total

    min_ticket = 0.5 * CRORE
    orders = []
    for tk, r in sorted(rupees.items(), key=lambda x: x[1], reverse=True):
        if r < min_ticket:
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
        if r < min_ticket:
            continue
        sellable_value = h["sellable_shares"] * h["price"]
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
        delta = h["target_weight"] * scale / 100 * ds["aum"] - h["market_value"]
        if abs(delta) < min_ticket:
            continue
        if delta > 0:
            shares = int(delta // h["price"])
            if shares > 0:
                orders.append(_order(ds, h["ticker"], "BUY", shares=shares))
        else:
            sellable_value = h["sellable_shares"] * h["price"]
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
    lim = data.COMPLIANCE_LIMITS
    checks = []

    delta = {}
    for o in orders:
        sign = 1 if o["side"] == "BUY" else -1
        delta[o["ticker"]] = delta.get(o["ticker"], 0.0) + sign * o["est_value"]

    def st(projected, limit):
        return "FAIL" if projected > limit else ("WARN" if projected >= 0.9 * limit else "PASS")

    for ticker, d in delta.items():
        if d <= 0:
            continue
        h = data.holding(ds, ticker)
        current = h["weight"] if h else 0.0
        projected = round(current + d / aum * 100, 2)
        checks.append({"code": "SEBI-10PCT", "rule": "Single issuer limit", "entity": ticker,
                       "current": current, "projected": projected, "limit": lim["single_issuer_limit"],
                       "status": st(projected, lim["single_issuer_limit"]),
                       "message": f"{ticker} projected weight {projected}% vs limit {lim['single_issuer_limit']}%."})

    for sector in (sectors or []):
        buy_into = sum(d for tk, d in delta.items() if d > 0 and _sector_for(ds, tk) == sector)
        current = data.sector_weight(ds, sector)
        projected = round(current + buy_into / aum * 100, 2)
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
        projected = round(current + d / aum * 100, 2)
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
                    shares = int(min(remaining, h["sellable_shares"] * h["price"]) // h["price"])
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
        seen.add(h["ticker"])
        out.append({"ticker": h["ticker"], "price": h["price"],
                    "current_value": h["market_value"], "expected_return": returns.get(h["ticker"], 0.0)})
    for u in data.UNIVERSE:
        if u["ticker"] in seen:
            continue
        if sectors and u["sector"] not in sectors:
            continue
        held = data.holding(ds, u["ticker"])
        out.append({"ticker": u["ticker"], "price": u["price"],
                    "current_value": held["market_value"] if held else 0.0,
                    "expected_return": returns.get(u["ticker"], 0.0)})
    return out


def _sell_candidates(ds, sectors, returns):
    return [{"ticker": h["ticker"], "price": h["price"], "sellable_shares": h["sellable_shares"],
             "expected_return": returns.get(h["ticker"], 0.0)}
            for h in ds["holdings"]
            if (not sectors or h["sector"] in sectors) and h["sellable_shares"] > 0]


def _orders_by_optimizer(ds, action, sectors, amount, investable, returns):
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
        allocations, opt_meta = optimizer.optimize_buy(candidates, amount, aum, _ISSUER_CAP_FRAC)
        for a in allocations:
            orders.append({**_order(ds, a["ticker"], "BUY", shares=a["shares"]),
                           "reason": "Convex-optimized to maximize forecast return"})
        buy_total = sum(o["est_value"] for o in orders)
        gap = buy_total - investable
        if gap > 0:
            sells, notes = _funding_sells(ds, gap, exclude_sectors=sectors or None)
            funding_sources, orders = sells, orders + sells
            risk_notes.extend(notes)
            warnings.append(f"Purchase exceeds investable cash by ~Rs {gap / CRORE:,.1f} Cr; funded by trimming holdings.")
        elif action == "contribution":
            funding_sources = [{"ticker": "INFLOW", "name": "Contribution / subscription inflow",
                                "sector": "Cash", "side": "IN", "shares": 0, "price": 0,
                                "est_value": amount, "reason": "New cash deployed by convex optimizer to maximize forecast return."}]
        else:
            funding_sources = [{"ticker": "CASH", "name": "Available cash", "sector": "Cash",
                                "side": "USE", "shares": 0, "price": 0, "est_value": buy_total,
                                "reason": "Fully funded from investable cash."}]

    elif action in ("redemption", "decrease", "sell", "trim", "raise_cash"):
        sec = sectors if action in ("decrease", "sell", "trim") else None
        candidates = _sell_candidates(ds, sec, returns)
        sells, opt_meta = optimizer.optimize_sell(candidates, amount)
        for sdict in sells:
            orders.append({**_order(ds, sdict["ticker"], "SELL", shares=sdict["shares"]),
                           "reason": "Convex-optimized to minimize forecast return given up"})
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
            if abs(delta) < min_ticket or not h:
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
# Public entry point
# --------------------------------------------------------------------------- #
def generate_plan(fund_id, intent):
    ds = data.get_ds(fund_id)
    action = (intent.get("action") or "contribution").lower()
    target = intent.get("target") or ""
    amount = float(intent.get("amount_cr") or 0) * CRORE
    horizon = int(intent.get("horizon_days") or 5)

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
    cfp = cash_flow_planning(ds, horizon)
    investable = cfp["investable_amount"]

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
                    ds, action, sectors, amount, investable, returns)
            except Exception as exc:  # solver / feasibility issue -> fall back
                method_used = "rules"
                orders, funding_sources, risk_notes, warnings = _orders_by_rules(
                    ds, action, sectors, amount, investable, target)
                warnings.append(f"Convex optimization failed ({exc}); fell back to rule-based allocation.")
    else:
        orders, funding_sources, risk_notes, warnings = _orders_by_rules(
            ds, action, sectors, amount, investable, target)

    # Annotate every order with its forecast expected 1-month return.
    for o in orders:
        o["expected_return"] = round(returns.get(o["ticker"], forecast.expected_return(o["ticker"])), 4)

    compliance = _compliance_checks(ds, orders, sectors)
    risks = _risk_flags(ds, orders, risk_notes, horizon)

    total_buy = sum(o["est_value"] for o in orders if o["side"] == "BUY")
    total_sell = sum(o["est_value"] for o in orders if o["side"] == "SELL")
    net_cash = total_sell - total_buy

    has_fail = any(c["status"] == "FAIL" for c in compliance)
    has_warn = any(c["status"] == "WARN" for c in compliance) or any(r["severity"] == "HIGH" for r in risks)
    if has_fail:
        recommendation = "Plan breaches one or more compliance limits. Recommend MODIFY or ESCALATE before execution."
    elif has_warn:
        recommendation = "Plan is executable but has items near limits / elevated execution risk. Recommend REVIEW carefully, then APPROVE with monitoring."
    else:
        recommendation = "Plan is within all limits with low execution risk. Recommend APPROVE for execution."

    # Pending trades that affect this plan's cash picture (shown for full context).
    pending = [{**t, "gross_value_cr": round(t["gross_value"] / CRORE, 2),
                "cash_impact_cr": round(t["cash_impact"] / CRORE, 2)} for t in ds["pending_trades"]]

    return {
        "plan_id": f"PLAN-{uuid.uuid4().hex[:8].upper()}",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "fund": {"fund_id": ds["id"], "name": ds["fund"]["name"], "aum_cr": round(ds["aum"] / CRORE, 2)},
        "intent": {"action": action, "target": target, "targets": raw_targets,
                   "resolved_sector": sectors[0] if len(sectors) == 1 else None,
                   "resolved_sectors": sectors,
                   "amount_cr": intent.get("amount_cr"), "horizon_days": horizon, "note": intent.get("note"),
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
            "compliance_status": "FAIL" if has_fail else ("WARN" if has_warn else "PASS"),
        },
        "warnings": warnings, "recommendation": recommendation, "status": "Pending PIC Review",
    }
