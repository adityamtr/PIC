"""
Compute stock-level and fund-level risk/return metrics and write them as
processed CSVs alongside the other files in ``data/processed/final``.

This implements the formulas in ``docs/nav-risk-return-metrics.md``
(annualized return, 1M/3M/6M return, annualized volatility, max drawdown,
Sharpe, Sortino) against the data we actually have:

  * Stock level: built directly from the monthly adjusted-close series in
    ``data/processed/final/stock_macro_monthly_target.csv`` (one row per ISIN).
  * Fund level: there is no ingested fund NAV history (``funds.nav`` is a single
    current snapshot), so the fund-level series is *derived synthetically* by
    applying each fund's current holding weights (from ``app.data_v2``, the
    real disclosure-based holdings) to the historical stock return panel:
    r_portfolio,t = sum_i w_i * r_i,t. Metrics are then computed on that
    synthetic series the same way as at the stock level. Each fund row also
    carries a strategy range (``strategy_return_low/high``,
    ``strategy_volatility_low/high``) computed from that *same* synthetic
    series: the 20th/80th percentile of annualized return/volatility across
    rolling 3-year windows (``_rolling_window_stats``) — i.e. "the range this
    fund's own current-weight book has typically landed in historically",
    not a hand-picked guess. A fund without enough history for rolling
    windows falls back to a band sized off risk_grade around its single
    full-history point.

Outputs (seeded into SQLite by ``scripts/init_db.py`` -> ``stock_risk_return_metrics`` /
``fund_risk_return_metrics`` tables):
  * data/processed/final/stock_risk_return_metrics.csv
  * data/processed/final/fund_risk_return_metrics.csv

Note on periodicity: the source data is *monthly*, not daily, so "1M/3M/6M"
below means 1/3/6 monthly observations (not 21/63/126 trading days as in the
docs, which assumed a daily series), and annualization uses 12 periods/year.

Usage (from the `backend/` directory or anywhere):

    python scripts/compute_risk_return_metrics.py
    python scripts/compute_risk_return_metrics.py --risk-free-rate 0.07
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent               # <repo>/backend
REPO_ROOT = BACKEND_DIR.parent                # <repo>

DATA_FINAL_DIR = REPO_ROOT / "data" / "processed" / "final"
TARGET_CSV = DATA_FINAL_DIR / "stock_macro_monthly_target.csv"

STOCK_METRICS_CSV = DATA_FINAL_DIR / "stock_risk_return_metrics.csv"
FUND_METRICS_CSV = DATA_FINAL_DIR / "fund_risk_return_metrics.csv"

PERIODS_PER_YEAR = 12  # monthly observations

# India ~10Y G-Sec proxy; override with --risk-free-rate if a different anchor
# is preferred. This is an assumption, not an ingested rate.
DEFAULT_RISK_FREE_RATE = 0.065

# Minimum monthly observations required before annualized metrics are trusted.
MIN_OBSERVATIONS = 12

# Rolling-window strategy band: the fund's own historical range, not a guess.
# Each window is annualized independently, then the low/high percentiles across
# all windows become the mandate band (see _rolling_window_stats).
ROLLING_WINDOW_MONTHS = 36
BAND_LOW_PERCENTILE = 20
BAND_HIGH_PERCENTILE = 80
MIN_ROLLING_WINDOWS = 12

# Fallback band (fraction of the computed full-history point) used only when a
# fund's synthetic series is too short for rolling windows.
RISK_GRADE_BAND_PCT = {
    "Low": 0.10,
    "Moderate": 0.15,
    "High": 0.20,
    "Very High": 0.25,
}
DEFAULT_BAND_PCT = 0.20

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


# --------------------------------------------------------------------------- #
# Shared metric math
# --------------------------------------------------------------------------- #
def _annualized_return(returns: pd.Series) -> float:
    growth = (1.0 + returns).prod()
    n = len(returns)
    if n == 0 or growth <= 0:
        return float("nan")
    return float(growth ** (PERIODS_PER_YEAR / n) - 1.0)


def _annualized_volatility(returns: pd.Series) -> float:
    if len(returns) < 2:
        return float("nan")
    return float(returns.std(ddof=1) * np.sqrt(PERIODS_PER_YEAR))


def _max_drawdown(level: pd.Series) -> float:
    running_max = level.cummax()
    drawdown = (running_max - level) / running_max
    return float(drawdown.max())


def _sharpe(annual_return: float, annual_vol: float, risk_free_rate: float) -> float:
    if not annual_vol or np.isnan(annual_vol) or annual_vol == 0:
        return float("nan")
    return float((annual_return - risk_free_rate) / annual_vol)


def _sortino(returns: pd.Series, annual_return: float, risk_free_rate: float) -> float:
    period_rf = risk_free_rate / PERIODS_PER_YEAR
    downside = (returns - period_rf).clip(upper=0.0)
    downside_dev = float(np.sqrt((downside ** 2).mean()) * np.sqrt(PERIODS_PER_YEAR))
    if not downside_dev or np.isnan(downside_dev) or downside_dev == 0:
        return float("nan")
    return float((annual_return - risk_free_rate) / downside_dev)


def _rolling_window_stats(
    returns: pd.Series, window: int = ROLLING_WINDOW_MONTHS
) -> tuple[np.ndarray, np.ndarray]:
    """Annualized return/volatility of every overlapping ``window``-month slice
    of ``returns``. Used to derive a fund's strategy band from its own
    historical range instead of a hand-picked assumption."""
    values = returns.to_numpy()
    n = len(values)
    if n < window:
        return np.array([]), np.array([])
    rets, vols = [], []
    for start in range(0, n - window + 1):
        chunk = values[start:start + window]
        growth = float(np.prod(1.0 + chunk))
        rets.append(growth ** (PERIODS_PER_YEAR / window) - 1.0 if growth > 0 else np.nan)
        vols.append(float(np.std(chunk, ddof=1)) * np.sqrt(PERIODS_PER_YEAR))
    return np.array(rets), np.array(vols)


def _metrics_from_returns(
    returns: pd.Series, level: pd.Series, risk_free_rate: float
) -> dict:
    """Shared metric block for a clean (no-NaN) return series + its rebased level series."""
    n = len(returns)
    annual_return = _annualized_return(returns)
    annual_vol = _annualized_volatility(returns)
    return {
        "n_obs": n,
        "return_1m": float(returns.iloc[-1]) if n >= 1 else float("nan"),
        "return_3m": float((1 + returns.tail(3)).prod() - 1) if n >= 3 else float("nan"),
        "return_6m": float((1 + returns.tail(6)).prod() - 1) if n >= 6 else float("nan"),
        "annualized_return": annual_return,
        "annualized_volatility": annual_vol,
        "max_drawdown": _max_drawdown(level) if n >= 1 else float("nan"),
        "sharpe_ratio": _sharpe(annual_return, annual_vol, risk_free_rate),
        "sortino_ratio": _sortino(returns, annual_return, risk_free_rate),
    }


# --------------------------------------------------------------------------- #
# Stock level
# --------------------------------------------------------------------------- #
def load_stock_panel(data_path: Path = TARGET_CSV) -> pd.DataFrame:
    df = pd.read_csv(data_path)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(["isin", "date"]).reset_index(drop=True)
    # adj_close accounts for splits/dividends; fall back to close where absent.
    df["level"] = df["monthly_adj_close"].fillna(df["monthly_close"])
    df["period_return"] = df.groupby("isin")["level"].pct_change()
    return df


def compute_stock_metrics(df: pd.DataFrame, risk_free_rate: float) -> pd.DataFrame:
    rows = []
    for isin, group in df.groupby("isin"):
        group = group.dropna(subset=["period_return"])
        if len(group) < MIN_OBSERVATIONS:
            continue
        symbol = group["symbol"].dropna().iloc[-1] if group["symbol"].notna().any() else None
        metrics = _metrics_from_returns(
            group["period_return"], group["level"], risk_free_rate
        )
        rows.append({
            "isin": isin,
            "symbol": symbol,
            "as_of_date": group["date"].max().date().isoformat(),
            **metrics,
        })
    return pd.DataFrame(rows).sort_values("isin").reset_index(drop=True)


# --------------------------------------------------------------------------- #
# Fund level (synthetic: current weights applied to stock return history)
# --------------------------------------------------------------------------- #
def _band_pct(risk_grade: str | None) -> float:
    return RISK_GRADE_BAND_PCT.get(risk_grade or "", DEFAULT_BAND_PCT)


def compute_fund_metrics(
    stock_panel: pd.DataFrame, risk_free_rate: float
) -> pd.DataFrame:
    from app import data_v2  # heavy import: parses XLSX disclosures + price feed

    returns_wide = stock_panel.pivot_table(
        index="date", columns="isin", values="period_return"
    ).sort_index()

    datasets = data_v2.build_datasets_from_source()

    rows = []
    for fund_id, ds in datasets.items():
        weights = {
            h["isin"]: h["weight"]
            for h in ds["holdings"]
            if h.get("isin") in returns_wide.columns and h.get("weight")
        }
        if not weights:
            continue

        isins = list(weights.keys())
        w = pd.Series(weights, dtype=float)
        w = w / w.sum() * 100.0  # renormalize to the mapped subset

        fund_returns = returns_wide[isins]
        # Per-date weighted average over whichever holdings have data that
        # month, renormalizing weights so a missing history for one name
        # doesn't truncate the whole series.
        available_weight = fund_returns.notna().mul(w, axis=1).sum(axis=1)
        weighted_sum = fund_returns.fillna(0.0).mul(w, axis=1).sum(axis=1)
        synthetic_return = (weighted_sum / available_weight).where(available_weight > 0)
        synthetic_return = synthetic_return.dropna()
        if len(synthetic_return) < MIN_OBSERVATIONS:
            continue

        synthetic_level = (1.0 + synthetic_return).cumprod()
        metrics = _metrics_from_returns(synthetic_return, synthetic_level, risk_free_rate)
        annual_return = metrics["annualized_return"]
        annual_vol = metrics["annualized_volatility"]

        roll_rets, roll_vols = _rolling_window_stats(synthetic_return)
        roll_rets = roll_rets[~np.isnan(roll_rets)]
        if len(roll_rets) >= MIN_ROLLING_WINDOWS and len(roll_vols) >= MIN_ROLLING_WINDOWS:
            # Data-driven band: the range this fund's own current-weight book
            # has actually landed in across rolling 3-year windows of its own
            # history — not a hand-picked guess, so it can't drift away from
            # what the "current" point measures the same way.
            range_source = "rolling_percentile"
            return_low = float(np.percentile(roll_rets, BAND_LOW_PERCENTILE))
            return_high = float(np.percentile(roll_rets, BAND_HIGH_PERCENTILE))
            vol_low = float(np.percentile(roll_vols, BAND_LOW_PERCENTILE))
            vol_high = float(np.percentile(roll_vols, BAND_HIGH_PERCENTILE))
        else:
            # Not enough history for rolling windows: fall back to a generic
            # band around the single full-history point, sized off risk_grade.
            range_source = "risk_grade_fallback"
            band = _band_pct(ds["fund"].get("risk_grade"))
            return_low = annual_return - band * abs(annual_return) if pd.notna(annual_return) else float("nan")
            return_high = annual_return + band * abs(annual_return) if pd.notna(annual_return) else float("nan")
            vol_low = max(annual_vol * (1 - band), 0.0) if pd.notna(annual_vol) else float("nan")
            vol_high = annual_vol * (1 + band) if pd.notna(annual_vol) else float("nan")

        rows.append({
            "fund_id": fund_id,
            "fund_name": ds["fund"].get("name"),
            "category": ds["fund"].get("category"),
            "risk_grade": ds["fund"].get("risk_grade"),
            "as_of_date": stock_panel["date"].max().date().isoformat(),
            "mapped_holdings": len(isins),
            "mapped_weight_pct": round(float(sum(weights.values())), 4),
            **metrics,
            "strategy_range_source": range_source,
            "strategy_return_low": return_low,
            "strategy_return_high": return_high,
            "strategy_volatility_low": vol_low,
            "strategy_volatility_high": vol_high,
        })

    return pd.DataFrame(rows).sort_values("fund_id").reset_index(drop=True)


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compute stock- and fund-level risk/return metrics and write processed CSVs."
    )
    parser.add_argument("--data-path", type=Path, default=TARGET_CSV)
    parser.add_argument("--stock-out", type=Path, default=STOCK_METRICS_CSV)
    parser.add_argument("--fund-out", type=Path, default=FUND_METRICS_CSV)
    parser.add_argument("--risk-free-rate", type=float, default=DEFAULT_RISK_FREE_RATE)
    args = parser.parse_args()

    print(f"Loading stock panel: {args.data_path}")
    panel = load_stock_panel(args.data_path)

    print("Computing stock-level metrics ...")
    stock_metrics = compute_stock_metrics(panel, args.risk_free_rate)
    args.stock_out.parent.mkdir(parents=True, exist_ok=True)
    stock_metrics.to_csv(args.stock_out, index=False)
    print(f"  wrote {len(stock_metrics)} rows -> {args.stock_out}")

    print("Computing fund-level metrics (synthetic, current-weight derived) ...")
    fund_metrics = compute_fund_metrics(panel, args.risk_free_rate)
    args.fund_out.parent.mkdir(parents=True, exist_ok=True)
    fund_metrics.to_csv(args.fund_out, index=False)
    print(f"  wrote {len(fund_metrics)} rows -> {args.fund_out}")


if __name__ == "__main__":
    main()
