"""
Convex-optimization allocation engine (CVXPY), adapted from the `mozart`
prototype for the PIC data model.

Given forecast expected returns (from `forecast.py`, ultimately a TFT), this
module decides the fund's allocation by solving small convex programs instead of
using fixed rule-of-thumb weights:

  - `optimize_buy`      deploy cash into the names with the best expected return,
                        subject to long-only, per-issuer caps and a per-name
                        diversification cap.
  - `optimize_sell`     raise a target amount by selling the names we expect to
                        return the least (the `mozart` "removal" problem),
                        respecting lock-ins (sellable shares only).
  - `optimize_rebalance` retilt the whole book toward higher expected return
                        within an issuer cap and a turnover budget.

Everything is expressed in rupees. cvxpy is an optional dependency: if it is not
installed the planner falls back to the existing rule-based logic, so the app
still runs. Import failures are swallowed here and surfaced via `available()`.
"""

from __future__ import annotations

try:  # optional dependency — planner degrades to rules if missing
    import cvxpy as cp
    import numpy as np
    _IMPORT_ERROR = None
except Exception as exc:  # pragma: no cover - depends on environment
    cp = None
    np = None
    _IMPORT_ERROR = str(exc)


class OptimizerUnavailable(RuntimeError):
    """Raised when cvxpy is not installed / importable."""


class OptimizationFailed(RuntimeError):
    """Raised when the solver does not reach an (near-)optimal solution."""


def available() -> bool:
    return cp is not None


def import_error() -> str | None:
    return _IMPORT_ERROR


def _require():
    if cp is None:
        raise OptimizerUnavailable(
            f"cvxpy is not available ({_IMPORT_ERROR}); install backend requirements to enable "
            "convex optimization."
        )


# Money terms are scaled to crore before solving. Raw rupee magnitudes (~1e9)
# against tiny return coefficients (~0.02) are badly conditioned and make solvers
# fail; working in crore keeps everything O(1e2–1e4).
_UNIT = 10_000_000  # 1 crore
_OK = {"optimal", "optimal_inaccurate"}


def _exposure_constraints(context, changes_by_ticker, limits):
    """Build hard projected-exposure constraints in crore units."""
    if not context:
        return []

    current = context.get("current_values_crore", {})
    entities = context.get("entities", {})
    aum = context["aum_crore"]
    safety_margin = max(1e-6, 1e-8 * aum)  # solver-scale headroom in crore
    constraints = []

    dimensions = [("issuer", None), ("sector", "sector"), ("group", "group"),
                  ("country", "country")]
    for limit_name, entity_key in dimensions:
        limit = limits.get(limit_name)
        if limit is None:
            continue
        buckets = {}
        tickers = set(current) | set(changes_by_ticker)
        for ticker in tickers:
            key = ticker if entity_key is None else entities.get(ticker, {}).get(entity_key)
            if key is not None:
                buckets.setdefault(key, []).append(ticker)
        for key, tickers_in_bucket in buckets.items():
            if not any(ticker in changes_by_ticker for ticker in tickers_in_bucket):
                continue
            base = sum(current.get(ticker, 0.0) for ticker in tickers_in_bucket)
            change = sum((changes_by_ticker.get(ticker, 0.0) for ticker in tickers_in_bucket), 0.0)
            bucket_limit = limit.get(key) if isinstance(limit, dict) else limit
            if bucket_limit is None:
                continue
            hard_maximum = bucket_limit * aum
            maximum = (base if base > hard_maximum
                       else hard_maximum - safety_margin)
            constraints.append(base + change <= maximum)
    return constraints


def _risk_constraint(weight_by_ticker: dict, risk: dict):
    """Build the initial convex ``w^T Sigma w <= target^2 / 12`` bound over
    whichever tickers the caller has a weight expression for. ``risk`` is the
    dict planner._build_risk_context() produces: {tickers, cov_monthly,
    target_volatility, ...}. Tickers in risk["tickers"] missing from
    weight_by_ticker (shouldn't normally happen) are skipped."""
    tickers = [t for t in risk["tickers"] if t in weight_by_ticker]
    if len(tickers) < 2:
        return None
    idx = [risk["tickers"].index(t) for t in tickers]
    cov = risk["cov_monthly"][np.ix_(idx, idx)]
    w = cp.hstack([weight_by_ticker[t] for t in tickers])
    target = risk.get("target_volatility", risk.get("sigma_max_annual"))
    sigma_max_monthly_var = (target ** 2) / 12.0
    return cp.quad_form(w, cov) <= sigma_max_monthly_var


def _fit_risk_target(x0, risk, weights_for_x, constraints, bounds):
    """Move a feasible allocation toward the requested annualized volatility.

    The target can be infeasible under the allocation constraints; in that
    case SLSQP returns the closest feasible point it found, and the caller can
    report the achieved volatility alongside the target.
    """
    target = (risk or {}).get("target_volatility") or (risk or {}).get("sigma_max_annual")
    if target is None or target < 0:
        return x0, None

    from scipy.optimize import minimize

    covariance = np.asarray(risk["cov_monthly"], dtype=float)

    def annualized_volatility(values):
        weights = np.asarray(weights_for_x(values), dtype=float)
        monthly_variance = float(weights @ covariance @ weights)
        return float(np.sqrt(max(monthly_variance, 0.0) * 12.0))

    initial = np.asarray(x0, dtype=float)
    scale = max(float(target), 0.01)

    def objective(values):
        target_gap = (annualized_volatility(values) - target) / scale
        return target_gap * target_gap + 1e-9 * float(np.sum((values - initial) ** 2))

    result = minimize(
        objective, initial, method="SLSQP", bounds=bounds, constraints=constraints,
        options={"ftol": 1e-12, "maxiter": 500},
    )
    chosen = result.x if result.success and np.all(np.isfinite(result.x)) else initial
    return chosen, annualized_volatility(chosen)


def _solve_continuous(prob):
    """Try a few solvers in order; return the status of the first that lands on
    an (near-)optimal solution, else the last status seen."""
    last = None
    for solver in ("CLARABEL", "ECOS", "SCS"):
        try:
            prob.solve(solver=getattr(cp, solver))
        except Exception:
            continue
        last = prob.status
        if prob.status in _OK:
            return solver, prob.status
    return last or "no_solver", (prob.status or "failed")


# --------------------------------------------------------------------------- #
# Buy: deploy `amount` to maximize expected return of deployed capital
# --------------------------------------------------------------------------- #
def optimize_buy(candidates, amount, aum, issuer_cap_frac, max_name_frac=0.34,
                 sector_cap_frac=None, sector_current=None, cap_aum=None, risk=None,
                 exposure_context=None, group_cap_frac=None, country_cap_by_name=None,
                 max_total_amount=None):
    """
    candidates: list of {ticker, price, current_value, expected_return, sector}
    amount:     rupees to deploy
    cap_aum:    AUM basis for the concentration caps. For a contribution this is
                the post-trade AUM (pre-trade AUM + deployed cash) so the caps
                match the policy check, which measures exposure against the
                post-trade book. Defaults to `aum`.
    sector_cap_frac / sector_current: if given, no sector's post-trade value may
                exceed sector_cap_frac of cap_aum. `sector_current` is the fund's
                existing rupee value per sector (across all holdings).
    risk:       optional dict from planner._build_risk_context() — constrains
                post-trade portfolio volatility to risk["sigma_max_annual"]
                (annualized) using a real monthly return covariance. Tickers
                outside `candidates` keep their current (fixed) weight in the
                constraint; the risk preference may be relaxed, while context
                exposure and cash limits remain hard constraints.
    exposure_context: current holdings and issuer/sector/group/country metadata
                used to enforce projected hard exposure limits.
    max_total_amount: optional hard ceiling on total deployed cash.
    Returns (allocations, meta) where allocations = [{ticker, rupees}] for the
    names the optimizer chose to buy.
    """
    _require()
    if not candidates or amount <= 0:
        return [], {"status": "skipped", "reason": "no candidates or zero amount"}

    n = len(candidates)
    ret = np.array([c["expected_return"] for c in candidates], dtype=float)
    cur = np.array([c["current_value"] for c in candidates], dtype=float) / _UNIT   # crore
    price = np.array([c["price"] for c in candidates], dtype=float)                 # rupees/share
    amount_u = amount / _UNIT
    cap_basis = (cap_aum if cap_aum is not None else aum)
    issuer_cap_u = issuer_cap_frac * cap_basis / _UNIT
    sectors = [c.get("sector") for c in candidates]
    sector_current = sector_current or {}

    buy = cp.Variable(n, nonneg=True)  # crore deployed per name

    risk_cons = None
    if risk:
        idx_by_ticker = {c["ticker"]: i for i, c in enumerate(candidates)}
        current_value_by_ticker = risk.get("current_value_by_ticker", {})
        weight_by_ticker = {}
        for t in risk["tickers"]:
            cur_frac = current_value_by_ticker.get(t, 0.0) / cap_basis
            weight_by_ticker[t] = (
                cur_frac + buy[idx_by_ticker[t]] * _UNIT / cap_basis if t in idx_by_ticker else cur_frac
            )
        risk_cons = _risk_constraint(weight_by_ticker, risk)

    exposure_limits = {
        "issuer": issuer_cap_frac,
        "sector": sector_cap_frac,
        "group": group_cap_frac,
        "country": country_cap_by_name,
    }

    def _build(with_name_cap, with_sector_cap, with_risk_cap):
        cons = [cp.sum(buy) == amount_u]
        if not exposure_context:
            cons.append(cur + buy <= issuer_cap_u)
        if max_total_amount is not None:
            cons.append(cp.sum(buy) <= max_total_amount / _UNIT)
        if exposure_context:
            changes = {candidate["ticker"]: buy[i] for i, candidate in enumerate(candidates)}
            cons.extend(_exposure_constraints(exposure_context, changes, exposure_limits))
        if with_name_cap:
            cons.append(buy <= max_name_frac * amount_u)
        if with_sector_cap and sector_cap_frac and not exposure_context:
            sector_cap_u = sector_cap_frac * cap_basis / _UNIT
            for s in sorted({x for x in sectors if x is not None}):
                idx = [i for i, x in enumerate(sectors) if x == s]
                cur_sector_u = sector_current.get(s, 0.0) / _UNIT
                cons.append(cur_sector_u + cp.sum(buy[idx]) <= sector_cap_u)
        if with_risk_cap and risk_cons is not None:
            cons.append(risk_cons)
        return cp.Problem(cp.Maximize(ret @ buy), cons)

    risk_applied = risk_cons is not None
    name_cap_applied = True
    sector_cap_applied = bool(sector_cap_frac)
    prob = _build(with_name_cap=True, with_sector_cap=True, with_risk_cap=risk_applied)
    solver, status = _solve_continuous(prob)
    if status not in _OK:
        # Diversification cap may make it infeasible for large tickets; relax the
        # per-name cap first, keeping the compliance issuer/sector caps and the
        # risk ceiling.
        name_cap_applied = False
        prob = _build(with_name_cap=False, with_sector_cap=True, with_risk_cap=risk_applied)
        solver, status = _solve_continuous(prob)
    if status not in _OK and risk_applied:
        # The user's risk ceiling is a preference, not a SEBI rule; relax it
        # next, ahead of the hard compliance caps.
        risk_applied = False
        prob = _build(with_name_cap=False, with_sector_cap=True, with_risk_cap=False)
        solver, status = _solve_continuous(prob)
    if status not in _OK:
        # Last resort: drop the sector cap so a plan is still produced; the
        # policy layer will surface any residual sector breach for review.
        sector_cap_applied = False
        prob = _build(with_name_cap=False, with_sector_cap=False, with_risk_cap=False)
        solver, status = _solve_continuous(prob)
    if status not in _OK:
        raise OptimizationFailed(f"buy optimization status: {status}")

    raw_rupees = np.clip(np.asarray(buy.value).flatten(), 0.0, None) * _UNIT
    target_volatility = None
    if risk and not exposure_context and max_total_amount is None:
        initial = raw_rupees / (_UNIT * amount_u)
        scipy_constraints = [
            {"type": "eq", "fun": lambda values: float(np.sum(values) - 1.0)},
            {"type": "ineq", "fun": lambda values: issuer_cap_u - cur - amount_u * values},
        ]
        bounds = [(0.0, max_name_frac if name_cap_applied else 1.0)] * n
        if sector_cap_applied and sector_cap_frac:
            sector_cap_u = sector_cap_frac * cap_basis / _UNIT
            for sector in sorted({value for value in sectors if value is not None}):
                indices = [i for i, value in enumerate(sectors) if value == sector]
                cur_sector_u = sector_current.get(sector, 0.0) / _UNIT
                scipy_constraints.append({
                    "type": "ineq",
                    "fun": lambda values, indices=indices, cur_sector_u=cur_sector_u:
                        sector_cap_u - cur_sector_u - amount_u * np.sum(values[indices]),
                })

        def _buy_weights(values):
            current_values = risk.get("current_value_by_ticker", {})
            index_by_ticker = {candidate["ticker"]: i for i, candidate in enumerate(candidates)}
            return np.array([
                (current_values.get(ticker, 0.0)
                 + (amount_u * values[index_by_ticker[ticker]] * _UNIT
                    if ticker in index_by_ticker else 0.0)) / cap_basis
                for ticker in risk["tickers"]
            ])

        fitted, target_volatility = _fit_risk_target(
            initial, risk, _buy_weights, scipy_constraints, bounds,
        )
        raw_rupees = np.clip(fitted, 0.0, None) * amount_u * _UNIT

    allocations = []
    for i, c in enumerate(candidates):
        shares = int(raw_rupees[i] // price[i]) if price[i] else 0
        if shares > 0:
            allocations.append({"ticker": c["ticker"], "price": price[i],
                                "rupees": raw_rupees[i], "shares": shares})

    deployed = float(ret @ raw_rupees)
    meta = {
        "status": status,
        "solver": solver,
        "objective": "maximize expected 1M return of deployed capital",
        "deployed_return_pct": round(deployed / amount * 100, 3) if amount else 0.0,
    }
    if risk is not None:
        meta["risk_constrained"] = risk_applied
        meta["initial_risk_bound_applied"] = risk_applied
        meta["sigma_max_annual"] = risk["sigma_max_annual"]
        meta["target_volatility"] = risk.get("target_volatility", risk["sigma_max_annual"])
        if target_volatility is not None:
            meta["risk_target_achieved_annual"] = round(target_volatility, 4)
    return allocations, meta


# --------------------------------------------------------------------------- #
# Sell: raise `amount` by selling the lowest expected-return names (removal)
# --------------------------------------------------------------------------- #
def optimize_sell(candidates, amount, max_name_frac=0.34, horizon_days=None, risk=None, aum=None,
                  exposure_context=None, issuer_cap_frac=None, sector_cap_frac=None,
                  group_cap_frac=None, country_cap_by_name=None):
    """
    candidates: list of {ticker, price, sellable_shares, expected_return,
                         tax_rate?, txn_rate?}
    amount:     rupees to raise
    risk:       optional dict from planner._build_risk_context() — constrains
                post-trade portfolio volatility to risk["sigma_max_annual"].
                Requires `aum` (the post-trade AUM basis) to express sell
                values as portfolio weights; skipped if `aum` is not given.
    Returns (sells, meta) where sells = [{ticker, shares}].

    This is the `mozart` removal idea (raise the target while giving up the least
    expected return), adapted for a real fund: solved as a continuous LP over
    sell *value* per name — bounded by each position's sellable value — then
    rounded to whole shares. A continuous LP is far more robust and faster than a
    31-name mixed-integer program with million-share bounds, and rounding at
    these sizes is immaterial.

    Tax-aware: the objective minimizes forfeited expected return PLUS the exit
    tax and transaction cost per rupee sold, so low-tax exits (LTCG lots, loss
    lots — negative tax_rate) are preferred over short-term winners. The
    forecast return is scaled over `horizon_days` (a ~21-trading-day month)
    because tax is a one-time cost while a predicted loss repeats — a
    persistent loser should be sold despite its tax bill.
    """
    _require()
    live = [c for c in candidates if c.get("sellable_shares", 0) > 0 and c["price"] > 0]
    if not live or amount <= 0:
        return [], {"status": "skipped", "reason": "no sellable candidates or zero amount"}

    n = len(live)
    ret = np.array([c["expected_return"] for c in live], dtype=float)
    tax = np.array([c.get("tax_rate", 0.0) for c in live], dtype=float)      # CGT per rupee sold
    txn = np.array([c.get("txn_rate", 0.0) for c in live], dtype=float)      # STT + charges per rupee
    horizon_scale = max(horizon_days, 1) / 21.0 if horizon_days else 1.0
    cost = ret * horizon_scale + tax + txn
    price = np.array([c["price"] for c in live], dtype=float)               # rupees/share
    sellable_u = np.array([c["sellable_shares"] * c["price"] for c in live], dtype=float) / _UNIT  # crore

    target_u = min(amount, float(sellable_u.sum()) * _UNIT) / _UNIT          # crore, capped at raiseable

    val = cp.Variable(n, nonneg=True)   # crore to sell per name

    risk_cons = None
    if risk and aum:
        idx_by_ticker = {c["ticker"]: i for i, c in enumerate(live)}
        current_value_by_ticker = risk.get("current_value_by_ticker", {})
        weight_by_ticker = {}
        for t in risk["tickers"]:
            cur_frac = current_value_by_ticker.get(t, 0.0) / aum
            weight_by_ticker[t] = (
                cur_frac - val[idx_by_ticker[t]] * _UNIT / aum if t in idx_by_ticker else cur_frac
            )
        risk_cons = _risk_constraint(weight_by_ticker, risk)

    exposure_limits = {
        "issuer": issuer_cap_frac,
        "sector": sector_cap_frac,
        "group": group_cap_frac,
        "country": country_cap_by_name,
    }

    def _build(with_name_cap, with_risk_cap, coeff):
        cons = [val <= sellable_u, cp.sum(val) == target_u]
        if exposure_context:
            changes = {candidate["ticker"]: -val[i] for i, candidate in enumerate(live)}
            cons.extend(_exposure_constraints(exposure_context, changes, exposure_limits))
        if with_name_cap:
            # Spread the raise so no single name funds most of it (market impact).
            cons.append(val <= max_name_frac * target_u)
        if with_risk_cap and risk_cons is not None:
            cons.append(risk_cons)
        # coeff @ val = horizon-scaled return given up + tax + txn cost (crore).
        return cp.Problem(cp.Minimize(coeff @ val), cons)

    def _solve(coeff):
        risk_applied = risk_cons is not None
        name_cap_applied = True
        prob = _build(True, risk_applied, coeff)
        solver, status = _solve_continuous(prob)
        if status not in _OK:
            # Too few names with capacity for the cap; relax it.
            name_cap_applied = False
            prob = _build(False, risk_applied, coeff)
            solver, status = _solve_continuous(prob)
        if status not in _OK and risk_applied:
            # The risk ceiling is a preference, not a hard constraint; relax it next.
            risk_applied = False
            prob = _build(False, False, coeff)
            solver, status = _solve_continuous(prob)
        if status not in _OK:
            raise OptimizationFailed(f"sell optimization status: {status}")
        values = np.clip(np.asarray(val.value).flatten(), 0.0, None) * _UNIT
        target_volatility = None
        if risk and not exposure_context:
            initial = values / (target_u * _UNIT)
            scipy_constraints = [{"type": "eq", "fun": lambda fractions: float(np.sum(fractions) - 1.0)}]
            bounds = [
                (0.0, min(float(cap), max_name_frac if name_cap_applied else 1.0))
                for cap in sellable_u / target_u
            ]
            if name_cap_applied:
                bounds = [(0.0, min(cap, max_name_frac)) for cap in sellable_u / target_u]

            def _sell_weights(fractions):
                current_values = risk.get("current_value_by_ticker", {})
                index_by_ticker = {candidate["ticker"]: i for i, candidate in enumerate(live)}
                return np.array([
                    (current_values.get(ticker, 0.0)
                     - (target_u * fractions[index_by_ticker[ticker]] * _UNIT
                        if ticker in index_by_ticker else 0.0)) / aum
                    for ticker in risk["tickers"]
                ])

            values_fit, target_volatility = _fit_risk_target(
                initial, risk, _sell_weights, scipy_constraints, bounds,
            )
            values = np.clip(values_fit, 0.0, None) * target_u * _UNIT
        return values, solver, status, risk_applied, target_volatility

    val_rupees, solver, status, risk_applied, target_volatility = _solve(cost)

    tax_aware = bool(np.any(tax != 0.0) or np.any(txn != 0.0))
    # Demo storytelling: what would the tax-blind plan have cost in tax?
    naive_tax_cr = None
    if tax_aware:
        try:
            naive_rupees, _, _, _, _ = _solve(ret * horizon_scale)
            naive_tax_cr = float((tax + txn) @ naive_rupees) / _UNIT
        except OptimizationFailed:
            naive_tax_cr = None

    sells, given_up, raised, est_tax, est_txn = [], 0.0, 0.0, 0.0, 0.0
    for i, c in enumerate(live):
        shares = int(val_rupees[i] // price[i])
        if shares > 0:
            value = shares * price[i]
            sells.append({"ticker": c["ticker"], "price": price[i], "shares": shares})
            given_up += ret[i] * value
            est_tax += tax[i] * value
            est_txn += txn[i] * value
            raised += value

    meta = {
        "status": status,
        "solver": solver,
        "objective": ("minimize horizon-scaled expected return given up + exit tax "
                      "+ transaction cost while raising the target"
                      if tax_aware else
                      "minimize expected 1M return given up (rupee-weighted) while raising the target"),
        "given_up_return_cr": round(given_up / _UNIT, 4),
        "amount_raised_cr": round(raised / _UNIT, 2),
    }
    if tax_aware:
        meta["est_tax_cr"] = round(est_tax / _UNIT, 4)
        meta["est_txn_cost_cr"] = round(est_txn / _UNIT, 4)
        meta["horizon_scale"] = round(horizon_scale, 3)
        if naive_tax_cr is not None:
            meta["tax_saved_vs_naive_cr"] = round(naive_tax_cr - (est_tax + est_txn) / _UNIT, 4)
    if risk is not None:
        meta["risk_constrained"] = risk_applied
        meta["initial_risk_bound_applied"] = risk_applied
        meta["sigma_max_annual"] = risk["sigma_max_annual"]
        meta["target_volatility"] = risk.get("target_volatility", risk["sigma_max_annual"])
        if target_volatility is not None:
            meta["risk_target_achieved_annual"] = round(target_volatility, 4)
    return sells, meta


# --------------------------------------------------------------------------- #
# Rebalance: retilt the whole book toward higher expected return
# --------------------------------------------------------------------------- #
def optimize_rebalance(holdings, aum, issuer_cap_frac, turnover_frac=0.15, risk=None,
                       sector_drift_frac=0.02, exposure_context=None, sector_cap_frac=None,
                       group_cap_frac=None, country_cap_by_name=None):
    """
    holdings: the fund's holdings (each has market_value, price, sellable_shares,
              expected_return).
    risk:     optional dict from planner._build_risk_context() — constrains the
              rebalanced book's volatility to risk["sigma_max_annual"]. Relaxed
              (with a warning-free silent drop, same as the turnover/issuer caps
              can't be) only if it alone makes the problem infeasible.
    Returns (targets, meta) where targets = [{ticker, delta_rupees}] — positive
    means buy, negative means sell. Maximizes expected return subject to an
    issuer cap and an L1 turnover budget, staying (near) cash-neutral.
    Sector weights are kept within ``sector_drift_frac`` of their current
    AUM-relative weights to avoid large cross-sector shifts.
    """
    _require()
    n = len(holdings)
    if n == 0:
        return [], {"status": "skipped"}

    ret = np.array([h["expected_return"] for h in holdings], dtype=float)
    w_cur = np.array([h["market_value"] / aum for h in holdings], dtype=float)
    invested = float(w_cur.sum())
    sector_indices = {}
    for i, holding in enumerate(holdings):
        sector = holding.get("sector")
        if sector:
            sector_indices.setdefault(sector, []).append(i)
    current_sector_weights = {
        sector: float(np.sum(w_cur[indices]))
        for sector, indices in sector_indices.items()
    }
    sellable_weight = np.array([
        max(float(h.get("sellable_shares", 0) or 0) * float(h.get("price", 0) or 0) / aum, 0.0)
        for h in holdings
    ])
    min_weight = np.maximum(w_cur - sellable_weight, 0.0)
    # Exit tax + transaction cost per rupee sold; penalizes realized gains so
    # the rebalance does not churn high-tax (short-term winner) positions.
    # Clipped at 0: a position at a net loss has a negative rate here, and
    # `-rate * cp.pos(...)` needs a nonneg coefficient to stay DCP-concave for
    # Maximize (loss-harvesting reward is already handled by optimize_sell).
    exit_cost = np.clip(np.array([
        (h.get("effective_tax_rate_pct", 0.0) or 0.0) / 100
        + (h.get("txn_cost_rate_pct", 0.0) or 0.0) / 100
        for h in holdings], dtype=float), 0.0, None)

    w = cp.Variable(n)
    base_cons = [
        cp.sum(w) == invested,        # stay as invested as we are now (cash-neutral)
        w >= min_weight,              # long-only; do not sell locked shares
        cp.norm1(w - w_cur) <= turnover_frac,   # limit churn
    ]
    if not exposure_context:
        base_cons.append(w <= issuer_cap_frac)
    else:
        current_values_crore = exposure_context.get("current_values_crore", {})
        changes = {
            holding["ticker"]: w[i] * (aum / _UNIT)
            - current_values_crore.get(holding["ticker"], 0.0)
            for i, holding in enumerate(holdings)
        }
        base_cons.extend(_exposure_constraints(
            exposure_context, changes,
            {"issuer": issuer_cap_frac, "sector": sector_cap_frac, "group": group_cap_frac,
             "country": country_cap_by_name},
        ))
    blocked_buys = [i for i, holding in enumerate(holdings) if holding.get("buy_blocked")]
    for i in blocked_buys:
        base_cons.append(w[i] <= w_cur[i])
    for sector, indices in sector_indices.items():
        current_weight = current_sector_weights[sector]
        sector_weight = cp.sum(w[indices])
        base_cons.extend([
            sector_weight >= max(current_weight - sector_drift_frac, 0.0),
            sector_weight <= current_weight + sector_drift_frac,
        ])
    tax_penalty = exit_cost @ cp.pos(w_cur - w)   # convex: tax applies to sells only

    risk_cons = None
    if risk:
        index_by_ticker = {h["ticker"]: i for i, h in enumerate(holdings)}
        weight_by_ticker = {t: w[index_by_ticker[t]] for t in risk["tickers"] if t in index_by_ticker}
        risk_cons = _risk_constraint(weight_by_ticker, risk)

    risk_applied = risk_cons is not None
    cons = base_cons + ([risk_cons] if risk_applied else [])
    prob = cp.Problem(cp.Maximize(ret @ w - tax_penalty), cons)
    solver, status = _solve_continuous(prob)
    if status not in _OK and risk_applied:
        # The risk ceiling is a preference, not a hard constraint; relax it
        # before giving up on the plan entirely.
        risk_applied = False
        prob = cp.Problem(cp.Maximize(ret @ w - tax_penalty), base_cons)
        solver, status = _solve_continuous(prob)
    if status not in _OK:
        raise OptimizationFailed(f"rebalance optimization status: {status}")

    w_new = np.asarray(w.value).flatten()
    target_volatility = None
    if risk and not exposure_context:
        index_by_ticker = {holding["ticker"]: i for i, holding in enumerate(holdings)}
        scipy_constraints = [
            {"type": "eq", "fun": lambda values: float(np.sum(values) - invested)},
            {"type": "ineq", "fun": lambda values: turnover_frac - float(np.sum(np.abs(values - w_cur)))},
        ]
        for sector, indices in sector_indices.items():
            current_weight = current_sector_weights[sector]
            scipy_constraints.extend([
                {"type": "ineq", "fun": lambda values, indices=indices, current_weight=current_weight:
                    float(np.sum(values[indices]) - current_weight + sector_drift_frac)},
                {"type": "ineq", "fun": lambda values, indices=indices, current_weight=current_weight:
                    float(current_weight + sector_drift_frac - np.sum(values[indices]))},
            ])

        def _rebalance_weights(values):
            return np.array([
                values[index_by_ticker[ticker]] if ticker in index_by_ticker else 0.0
                for ticker in risk["tickers"]
            ])

        w_new, target_volatility = _fit_risk_target(
            w_new, risk, _rebalance_weights, scipy_constraints,
            [(float(min_weight[i]), issuer_cap_frac) for i in range(n)],
        )
    targets = []
    for i, h in enumerate(holdings):
        delta = (w_new[i] - w_cur[i]) * aum
        targets.append({"ticker": h["ticker"], "delta_rupees": float(delta)})

    exp_pre = float(ret @ w_cur)
    exp_post = float(ret @ w_new)
    est_tax_cr = float(exit_cost @ np.clip(w_cur - w_new, 0.0, None)) * aum / _UNIT
    meta = {
        "status": status,
        "solver": solver,
        "objective": "maximize expected 1M return net of exit tax, within issuer cap + turnover budget",
        "est_tax_cr": round(est_tax_cr, 4),
        "expected_return_pre_pct": round(exp_pre * 100, 3),
        "expected_return_post_pct": round(exp_post * 100, 3),
        "turnover_budget_pct": round(turnover_frac * 100, 1),
        "sector_drift_limit_pct": round(sector_drift_frac * 100, 1),
    }
    if risk is not None:
        meta["risk_constrained"] = risk_applied
        meta["initial_risk_bound_applied"] = risk_applied
        meta["sigma_max_annual"] = risk["sigma_max_annual"]
        meta["target_volatility"] = risk.get("target_volatility", risk["sigma_max_annual"])
        if target_volatility is not None:
            meta["risk_target_achieved_annual"] = round(target_volatility, 4)
    return targets, meta
