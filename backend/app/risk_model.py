"""
Runtime risk model: builds a monthly return-covariance matrix from real price
history (``stock_prices``, via ``db.get_stock_price_levels``) for whichever
tickers the optimizer is considering, so ``optimizer.py`` can constrain a plan
to a target annualized volatility (``w^T Sigma w <= sigma_max^2``), per
``docs/nav-risk-return-metrics.md`` section 3.

Separate from ``scripts/compute_risk_return_metrics.py``: that script writes a
point-in-time *summary* (one row per stock/fund) consumed by the API for the
risk/return graph. This module computes the full covariance matrix needed by
the optimizer, on demand, for exactly the tickers in play.
"""

from __future__ import annotations

import numpy as np

from . import db

PERIODS_PER_YEAR = 12
MIN_OBSERVATIONS = 12


def _returns_by_isin(isins: list[str]) -> dict[str, dict[str, float]]:
    """``{isin: {date: period_return}}`` computed from price levels."""
    levels = db.get_stock_price_levels(isins) or {}
    out: dict[str, dict[str, float]] = {}
    for isin, series in levels.items():
        series = sorted(series)
        returns = {}
        prev = None
        for d, level in series:
            if prev and prev > 0:
                returns[d] = level / prev - 1.0
            prev = level
        out[isin] = returns
    return out


def _nearest_psd(cov: np.ndarray) -> np.ndarray:
    """Clip negative eigenvalues so cvxpy's ``quad_form`` accepts the matrix
    (sample covariance from a short/ragged history can be slightly indefinite)."""
    cov = (cov + cov.T) / 2.0
    eigvals, eigvecs = np.linalg.eigh(cov)
    eigvals = np.clip(eigvals, 1e-10, None)
    return (eigvecs * eigvals) @ eigvecs.T


def build_covariance(
    tickers: list[str], isin_by_ticker: dict[str, str]
) -> tuple[list[str], np.ndarray, list[str]]:
    """Build a monthly covariance matrix for ``tickers``.

    Returns ``(kept_tickers, cov_monthly, dropped_tickers)``. A ticker is
    dropped when it has no ISIN mapping or fewer than ``MIN_OBSERVATIONS``
    months of overlapping history with the rest of the set — the caller
    should fall back to a diagonal-only estimate for those (see
    ``diagonal_fallback_variance``).
    """
    isins = [isin_by_ticker[t] for t in tickers if isin_by_ticker.get(t)]
    returns_by_isin = _returns_by_isin(isins)

    candidate_tickers = [t for t in tickers if isin_by_ticker.get(t) in returns_by_isin]
    if len(candidate_tickers) < 2:
        return [], np.zeros((0, 0)), list(tickers)

    # Use the common (inner-join) date set across all candidates with enough
    # overlap; iteratively drop the ticker with the least overlap until every
    # remaining ticker clears MIN_OBSERVATIONS on the common date set.
    kept = list(candidate_tickers)
    while len(kept) >= 2:
        date_sets = [set(returns_by_isin[isin_by_ticker[t]].keys()) for t in kept]
        common = set.intersection(*date_sets)
        if len(common) >= MIN_OBSERVATIONS:
            break
        # Drop whichever ticker has the smallest individual history (likely
        # the one constraining the intersection).
        shortest = min(kept, key=lambda t: len(returns_by_isin[isin_by_ticker[t]]))
        kept.remove(shortest)
    else:
        kept = []

    if len(kept) < 2:
        return [], np.zeros((0, 0)), list(tickers)

    common_dates = sorted(set.intersection(
        *(set(returns_by_isin[isin_by_ticker[t]].keys()) for t in kept)
    ))
    matrix = np.array([
        [returns_by_isin[isin_by_ticker[t]][d] for d in common_dates]
        for t in kept
    ])  # tickers x dates
    cov_monthly = _nearest_psd(np.cov(matrix))
    dropped = [t for t in tickers if t not in kept]
    return kept, cov_monthly, dropped


def diagonal_fallback_variance(ticker: str, isin_by_ticker: dict[str, str],
                                stock_metrics: dict[str, dict], default_annual_vol: float) -> float:
    """Monthly variance estimate for a ticker missing from the covariance
    matrix: its own annualized_volatility if known, else a supplied default
    (typically the fund's own annualized_volatility)."""
    isin = isin_by_ticker.get(ticker)
    row = stock_metrics.get(isin) if isin else None
    annual_vol = (row or {}).get("annualized_volatility") or default_annual_vol
    return (annual_vol ** 2) / PERIODS_PER_YEAR


def extend_with_diagonal_fallback(
    kept: list[str], cov_monthly: np.ndarray, dropped: list[str],
    isin_by_ticker: dict[str, str], stock_metrics: dict[str, dict], default_annual_vol: float,
) -> tuple[list[str], np.ndarray]:
    """Append ``dropped`` tickers (too little/no overlapping price history to
    correlate) to the covariance as uncorrelated, diagonal-only entries using
    their own annualized_volatility (or ``default_annual_vol``).

    Without this, a ticker that build_covariance() couldn't place — e.g. a
    recently added holding with under a year of price history — would simply
    vanish from the risk constraint instead of contributing its own variance,
    silently understating portfolio risk for any book that holds it."""
    if not dropped:
        return kept, cov_monthly
    k, d = len(kept), len(dropped)
    extended = np.zeros((k + d, k + d))
    extended[:k, :k] = cov_monthly
    for i, ticker in enumerate(dropped):
        extended[k + i, k + i] = diagonal_fallback_variance(
            ticker, isin_by_ticker, stock_metrics, default_annual_vol)
    return kept + dropped, extended


def portfolio_annual_volatility(weights: np.ndarray, cov_monthly: np.ndarray) -> float:
    """Annualized portfolio volatility for weights (sum need not be 1) against a
    monthly covariance matrix."""
    monthly_var = float(weights @ cov_monthly @ weights)
    return float(np.sqrt(max(monthly_var, 0.0) * PERIODS_PER_YEAR))
