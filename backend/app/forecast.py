"""
Return-forecasting layer — PLACEHOLDER for the production TFT model.

The production design uses a Temporal Fusion Transformer (TFT) to predict each
stock's expected return over the next ~1 month. The convex optimizer
(`optimizer.py`) then consumes those predictions to decide the fund's
allocation.

The model is not built yet, so this module returns hard-coded *dummy* returns
with exactly the shape the real model will produce: a `{ticker -> expected
1-month return}` mapping (as a fraction, e.g. 0.024 = +2.4%). When the TFT is
ready, replace the body of `predict_returns` with a real inference call — the
rest of the app does not need to change.
"""

from __future__ import annotations

from . import data

MODEL_NAME = "TFT (placeholder)"
HORIZON_LABEL = "1 month"
IS_PLACEHOLDER = True

# Dummy expected 1-month returns per ticker (fraction). These stand in for the
# TFT's output. Values are illustrative only.
_DUMMY_1M_RETURNS = {
    # Information Technology
    "INFY": 0.024, "TCS": 0.021, "HCLTECH": 0.026, "LTIM": 0.019,
    "TECHM": 0.015, "WIPRO": 0.012, "MPHASIS": 0.028,
    # Financial Services
    "HDFCBANK": 0.018, "ICICIBANK": 0.022, "AXISBANK": 0.016, "KOTAKBANK": 0.014,
    "SBIN": 0.020, "BAJFINANCE": 0.027, "BAJAJFINSV": 0.019, "BAJAJHLDNG": 0.017,
    "MOTILALOFS": 0.030,
    # Energy / Utilities
    "RELIANCE": 0.015, "NTPC": 0.011, "ONGC": 0.008, "COALINDIA": 0.009,
    "POWERGRID": 0.010,
    # FMCG
    "ITC": 0.013, "HINDUNILVR": 0.010, "NESTLEIND": 0.009,
    # Automobile
    "MARUTI": 0.017, "M&M": 0.021, "TATAMOTORS": 0.014,
    # Healthcare
    "SUNPHARMA": 0.019, "CIPLA": 0.016, "DRREDDY": 0.012,
    # Others
    "BHARTIARTL": 0.020, "LT": 0.019, "TATASTEEL": 0.007,
    "ULTRACEMCO": 0.015, "GRASIM": 0.013, "TITAN": 0.018, "ASIANPAINT": 0.009,
}

# Fallback for any ticker the placeholder does not list explicitly.
_DEFAULT_RETURN = 0.010


def expected_return(ticker: str) -> float:
    """Predicted 1-month return (fraction) for one ticker."""
    return _DUMMY_1M_RETURNS.get(ticker, _DEFAULT_RETURN)


def predict_returns(tickers) -> dict[str, float]:
    """
    Predicted 1-month returns for a list of tickers.

    Placeholder: returns dummy values. The real TFT would take price/feature
    history and produce this same mapping.
    """
    return {t: expected_return(t) for t in tickers}


def _name_sector(ds, ticker):
    u = data.universe_entry(ticker)
    if u:
        return u["name"], u["sector"]
    h = data.holding(ds, ticker)
    if h:
        return h["name"], h["sector"]
    return ticker, "Unknown"


def forecast_rows(ds, tickers=None) -> list[dict]:
    """
    Build a display-ready, return-sorted forecast table.

    If `tickers` is omitted, covers the fund's current holdings plus the buyable
    universe — the names any plan for this fund could touch.
    """
    if tickers is None:
        relevant = {h["ticker"] for h in ds["holdings"]}
        relevant |= {u["ticker"] for u in data.UNIVERSE}
    else:
        relevant = set(tickers)

    rows = []
    for tk in relevant:
        name, sector = _name_sector(ds, tk)
        rows.append({
            "ticker": tk, "name": name, "sector": sector,
            "expected_return_1m": round(expected_return(tk), 4),
        })
    rows.sort(key=lambda r: r["expected_return_1m"], reverse=True)
    return rows


def summary(ds, tickers=None) -> dict:
    """Forecast block attached to a plan, for the UI to render."""
    return {
        "model": MODEL_NAME,
        "horizon": HORIZON_LABEL,
        "as_of": data.TODAY.isoformat(),
        "is_placeholder": IS_PLACEHOLDER,
        "note": "Dummy returns — placeholder until the TFT forecasting model is wired in.",
        "rows": forecast_rows(ds, tickers),
    }
