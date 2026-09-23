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
def optimize_buy(candidates, amount, aum, issuer_cap_frac, max_name_frac=0.34):
    """
    candidates: list of {ticker, price, current_value, expected_return}
    amount:     rupees to deploy
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
    issuer_cap_u = issuer_cap_frac * aum / _UNIT

    buy = cp.Variable(n, nonneg=True)  # crore deployed per name

    def _build(with_name_cap):
        cons = [cp.sum(buy) == amount_u, cur + buy <= issuer_cap_u]
        if with_name_cap:
            cons.append(buy <= max_name_frac * amount_u)
        return cp.Problem(cp.Maximize(ret @ buy), cons)

    prob = _build(with_name_cap=True)
    solver, status = _solve_continuous(prob)
    if status not in _OK:
        # Diversification cap may make it infeasible for large tickets; relax it.
        prob = _build(with_name_cap=False)
        solver, status = _solve_continuous(prob)
    if status not in _OK:
        raise OptimizationFailed(f"buy optimization status: {status}")

    raw_rupees = np.clip(np.asarray(buy.value).flatten(), 0.0, None) * _UNIT

    allocations = []
    for i, c in enumerate(candidates):
        shares = int(raw_rupees[i] // price[i]) if price[i] else 0
        if shares > 0:
            allocations.append({"ticker": c["ticker"], "rupees": raw_rupees[i], "shares": shares})

    deployed = float(ret @ raw_rupees)
    meta = {
        "status": status,
        "solver": solver,
        "objective": "maximize expected 1M return of deployed capital",
        "deployed_return_pct": round(deployed / amount * 100, 3) if amount else 0.0,
    }
    return allocations, meta


# --------------------------------------------------------------------------- #
# Sell: raise `amount` by selling the lowest expected-return names (removal)
# --------------------------------------------------------------------------- #
def optimize_sell(candidates, amount, max_name_frac=0.34):
    """
    candidates: list of {ticker, price, sellable_shares, expected_return}
    amount:     rupees to raise
    Returns (sells, meta) where sells = [{ticker, shares}].

    This is the `mozart` removal idea (raise the target while giving up the least
    expected return), adapted for a real fund: solved as a continuous LP over
    sell *value* per name — bounded by each position's sellable value — then
    rounded to whole shares. A continuous LP is far more robust and faster than a
    31-name mixed-integer program with million-share bounds, and rounding at
    these sizes is immaterial. The objective minimizes rupee-weighted expected
    return given up, so the lowest-forecast capital is liquidated first.
    """
    _require()
    live = [c for c in candidates if c.get("sellable_shares", 0) > 0 and c["price"] > 0]
    if not live or amount <= 0:
        return [], {"status": "skipped", "reason": "no sellable candidates or zero amount"}

    n = len(live)
    ret = np.array([c["expected_return"] for c in live], dtype=float)
    price = np.array([c["price"] for c in live], dtype=float)               # rupees/share
    sellable_u = np.array([c["sellable_shares"] * c["price"] for c in live], dtype=float) / _UNIT  # crore

    target_u = min(amount, float(sellable_u.sum()) * _UNIT) / _UNIT          # crore, capped at raiseable

    val = cp.Variable(n, nonneg=True)   # crore to sell per name

    def _build(with_name_cap):
        cons = [val <= sellable_u, cp.sum(val) == target_u]
        if with_name_cap:
            # Spread the raise so no single name funds most of it (market impact).
            cons.append(val <= max_name_frac * target_u)
        # ret @ val = expected 1M return (in crore) given up by selling that value.
        return cp.Problem(cp.Minimize(ret @ val), cons)

    prob = _build(with_name_cap=True)
    solver, status = _solve_continuous(prob)
    if status not in _OK:
        # Too few names with capacity for the cap; relax it.
        prob = _build(with_name_cap=False)
        solver, status = _solve_continuous(prob)
    if status not in _OK:
        raise OptimizationFailed(f"sell optimization status: {status}")

    val_rupees = np.clip(np.asarray(val.value).flatten(), 0.0, None) * _UNIT

    sells, given_up, raised = [], 0.0, 0.0
    for i, c in enumerate(live):
        shares = int(val_rupees[i] // price[i])
        if shares > 0:
            sells.append({"ticker": c["ticker"], "shares": shares})
            given_up += ret[i] * shares * price[i]
            raised += shares * price[i]

    meta = {
        "status": status,
        "solver": solver,
        "objective": "minimize expected 1M return given up (rupee-weighted) while raising the target",
        "given_up_return_cr": round(given_up / _UNIT, 4),
        "amount_raised_cr": round(raised / _UNIT, 2),
    }
    return sells, meta


# --------------------------------------------------------------------------- #
# Rebalance: retilt the whole book toward higher expected return
# --------------------------------------------------------------------------- #
def optimize_rebalance(holdings, aum, issuer_cap_frac, turnover_frac=0.15):
    """
    holdings: the fund's holdings (each has market_value, price, sellable_shares,
              expected_return).
    Returns (targets, meta) where targets = [{ticker, delta_rupees}] — positive
    means buy, negative means sell. Maximizes expected return subject to an
    issuer cap and an L1 turnover budget, staying (near) cash-neutral.
    """
    _require()
    n = len(holdings)
    if n == 0:
        return [], {"status": "skipped"}

    ret = np.array([h["expected_return"] for h in holdings], dtype=float)
    w_cur = np.array([h["market_value"] / aum for h in holdings], dtype=float)
    invested = float(w_cur.sum())

    w = cp.Variable(n)
    cons = [
        cp.sum(w) == invested,        # stay as invested as we are now (cash-neutral)
        w >= 0,                       # long-only
        w <= issuer_cap_frac,         # per-issuer cap
        cp.norm1(w - w_cur) <= turnover_frac,   # limit churn
    ]
    prob = cp.Problem(cp.Maximize(ret @ w), cons)
    solver, status = _solve_continuous(prob)
    if status not in _OK:
        raise OptimizationFailed(f"rebalance optimization status: {status}")

    w_new = np.asarray(w.value).flatten()
    targets = []
    for i, h in enumerate(holdings):
        delta = (w_new[i] - w_cur[i]) * aum
        targets.append({"ticker": h["ticker"], "delta_rupees": float(delta)})

    exp_pre = float(ret @ w_cur)
    exp_post = float(ret @ w_new)
    meta = {
        "status": status,
        "solver": solver,
        "objective": "maximize expected 1M return within issuer cap + turnover budget",
        "expected_return_pre_pct": round(exp_pre * 100, 3),
        "expected_return_post_pct": round(exp_post * 100, 3),
        "turnover_budget_pct": round(turnover_frac * 100, 1),
    }
    return targets, meta
