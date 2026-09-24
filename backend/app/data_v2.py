"""
Real-data dataset for two mutual funds: HDFC Flexi Cap and ICICI Prudential Large Cap.

Built from:
  - Raw disclosures (XLSX files)
  - data/processed/final/stock_macro_monthly_target.csv (latest share prices by ISIN)

Same shape/contract as data.py (FUND_SPECS, FUNDS, accessors) so routes can swap imports.
"""

from __future__ import annotations

import csv
from datetime import date, timedelta
from pathlib import Path

from . import xlsx_parser

CRORE = 10_000_000


def add_business_days(start: date, n: int) -> date:
    d, added, step = start, 0, (1 if n >= 0 else -1)
    while added < abs(n):
        d += timedelta(days=step)
        if d.weekday() < 5:
            added += 1
    return d


TODAY = date.today()

# Resolve paths relative to repo root (backend/app/data_v2.py is at <repo>/backend/app/)
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
HDFC_XLSX = REPO_ROOT / "data" / "raw" / "Funds Monthly Portfolio Disclosure(18 funds)" / "current" / "INF179K01UT0_HDFC Flexi Cap Fund.xlsx"
ICICI_XLSX = REPO_ROOT / "data" / "raw" / "Funds Monthly Portfolio Disclosure(18 funds)" / "current" / "INF109K016L0_ICICI Prudential Large Cap Fund.xlsx"
PRICES_CSV = REPO_ROOT / "data" / "processed" / "final" / "stock_macro_monthly_target.csv"


# --------------------------------------------------------------------------- #
# Load real data
# --------------------------------------------------------------------------- #
def _load_hdfc_holdings() -> list[dict]:
    """Load HDFC Flexi Cap holdings from XLSX."""
    if not HDFC_XLSX.exists():
        raise FileNotFoundError(f"HDFC XLSX file not found: {HDFC_XLSX}")
    return xlsx_parser.parse_hdfc_flexi_cap(HDFC_XLSX)


def _load_icici_holdings() -> list[dict]:
    """Load ICICI Large Cap holdings from XLSX."""
    if not ICICI_XLSX.exists():
        raise FileNotFoundError(f"ICICI XLSX file not found: {ICICI_XLSX}")
    return xlsx_parser.parse_icici_largecap(ICICI_XLSX)


def _load_prices() -> dict:
    """Load latest prices by ISIN from macro dataset."""
    if not PRICES_CSV.exists():
        raise FileNotFoundError(f"Prices file not found: {PRICES_CSV}")

    price_dict = {}
    with open(PRICES_CSV, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            isin = row.get("isin")
            if not isin:
                continue

            # Keep latest (max date) for each ISIN
            if isin not in price_dict or row.get("date", "") > price_dict[isin].get("date", ""):
                price = row.get("monthly_close")
                if not price or price.strip() == "":
                    price = row.get("monthly_adj_close")

                try:
                    price = float(price) if price else None
                except (ValueError, TypeError):
                    price = None

                symbol = row.get("symbol", isin)
                price_dict[isin] = {"price": price, "symbol": symbol, "date": row.get("date")}

    return price_dict


# Load once at module init
_HDFC_HOLDINGS = _load_hdfc_holdings()
_ICICI_HOLDINGS = _load_icici_holdings()
_PRICES_DICT = _load_prices()


# --------------------------------------------------------------------------- #
# Fund specifications
# --------------------------------------------------------------------------- #
FUND_SPECS_V2 = {
    "HDFC-FLEXICAP-DG": {
        "meta": {
            "fund_id": "HDFC-FLEXICAP-DG",
            "name": "HDFC Flexi Cap Fund",
            "amc": "HDFC Asset Management Company",
            "category": "Equity - Flexi Cap",
            "plan": "Direct - Growth",
            "benchmark": "NIFTY 500 TRI",
            "fund_manager": "Unknown",
            "inception": "Unknown",
            "nav": None,
            "expense_ratio": None,
            "risk_grade": "Very High",
        },
        "holdings_list": _HDFC_HOLDINGS,
        "pending": [
            ("PT-10231", "INFY",      "BUY",  40_000,  2072, 0, 1, "Unsettled"),
            ("PT-10232", "HDFCBANK", "SELL", 300_000, 1617, 0, 1, "Unsettled"),
            ("PT-10233", "RELIANCE",  "BUY",  25_000,  3097, -1, 2, "Unsettled"),
            ("PT-10234", "LT",        "SELL", 100_000, 3720, 0, 1, "Unsettled"),
            ("PT-10235", "ICICIBANK", "BUY",  20_000,  1196, -1, 2, "Unsettled"),
        ],
        "executed": [
            ("EX-10188", "ICICIBANK", "BUY",  60_000,  1196, -3, 1, "Settled"),
            ("EX-10190", "SBIN",      "BUY",  120_000, 826,  -3, 1, "Settled"),
            ("EX-10193", "RELIANCE",  "SELL", 200_000, 3097, -2, 1, "Settled"),
            ("EX-10195", "MARUTI",    "BUY",  4_000,   13500, -2, 1, "Settled"),
            ("EX-10199", "BHARTIARTL","BUY",  30_000,  1689, -1, 1, "Settled"),
        ],
        "corp": [
            ("RELIANCE", "Dividend", 10.0, 3, 10),
            ("INFY",     "Dividend", 18.0, 2, 9),
            ("ITC",      "Dividend", 6.5,  5, 12),
            ("TCS",      "Dividend", 27.0, 6, 14),
            ("HDFCBANK", "Dividend", 19.5, 8, 16),
        ],
    },
    "ICICIPRU-LARGECAP-DG": {
        "meta": {
            "fund_id": "ICICIPRU-LARGECAP-DG",
            "name": "ICICI Prudential Large Cap Fund",
            "amc": "ICICI Prudential Asset Management Company",
            "category": "Equity - Large Cap",
            "plan": "Direct - Growth",
            "benchmark": "NIFTY 100 TRI",
            "fund_manager": "Unknown",
            "inception": "Unknown",
            "nav": None,
            "expense_ratio": None,
            "risk_grade": "Very High",
        },
        "holdings_list": _ICICI_HOLDINGS,
        "pending": [
            ("PT-22101", "HDFCBANK", "BUY",  90_000,  1617, 0, 1, "Unsettled"),
            ("PT-22102", "RELIANCE", "SELL", 400_000, 3097, 0, 1, "Unsettled"),
            ("PT-22103", "MARUTI",   "BUY",  6_000,   13500, -1, 2, "Unsettled"),
            ("PT-22104", "INFY",     "BUY",  50_000,  2072, 0, 1, "Unsettled"),
        ],
        "executed": [
            ("EX-22050", "ICICIBANK", "BUY",  500_000, 1196, -3, 1, "Settled"),
            ("EX-22052", "LT",        "BUY",  800_000, 3720, -2, 1, "Settled"),
            ("EX-22055", "RELIANCE",  "SELL", 60_000,  3097, -2, 1, "Settled"),
            ("EX-22058", "AXISBANK",  "BUY",  120_000, 1048, -1, 1, "Settled"),
        ],
        "corp": [
            ("RELIANCE", "Dividend", 10.0, 3, 10),
            ("INFY",     "Dividend", 18.0, 2, 9),
            ("ITC",      "Dividend", 6.5,  5, 12),
            ("HDFCBANK", "Dividend", 19.5, 8, 16),
        ],
    },
}


# --------------------------------------------------------------------------- #
# Builder: turn a spec into a fully-computed dataset (ds)
# --------------------------------------------------------------------------- #
def _build_ds_v2(spec: dict) -> dict:
    """Build dataset from real holdings + prices."""
    fund_holdings = spec["holdings_list"]

    holdings = []
    unmapped_isins = []

    for holding_row in fund_holdings:
        isin = holding_row.get("isin", "")
        security_name = holding_row.get("name", "Unknown")
        industry = holding_row.get("industry", "Unknown")
        quantity = holding_row.get("quantity", 0)
        market_value = holding_row.get("market_value", 0)  # in Lacs
        percentage_nav = holding_row.get("percentage_nav", 0)

        # Normalize ICICI's fractional %NAV to percentage
        if percentage_nav < 1 and percentage_nav > 0:
            percentage_nav = percentage_nav * 100

        # Look up latest price
        price_info = _PRICES_DICT.get(isin)
        if price_info and price_info["price"] is not None:
            base_price = price_info["price"]
            ticker = price_info["symbol"]
        else:
            base_price = None
            ticker = isin  # fallback to ISIN
            unmapped_isins.append(isin)

        # Derive shares if we have price and market_value
        if base_price and base_price > 0 and market_value > 0:
            shares = round(market_value * CRORE / (base_price * 100_000))  # Convert from Lacs to Crores
        else:
            shares = quantity if quantity else 0

        holdings.append({
            "ticker": ticker,
            "name": security_name,
            "sector": industry,
            "group": industry,  # No separate group concept in real data
            "isin": isin,
            "price": base_price,
            "base_price": base_price,
            "shares": shares,
            "market_value": market_value * 100_000,  # Convert Lacs to normal units
            "target_weight": percentage_nav,
            "locked_shares": 0,
            "sellable_shares": shares,
            "lock_in_expiry": None,
            "lock_in_reason": None,
        })

    # Compute AUM and weights
    equity = sum(h["market_value"] for h in holdings)
    cash_total = 0  # Not in disclosure
    aum = equity if equity > 0 else 1  # Avoid div-by-zero

    for h in holdings:
        h["weight"] = round(h["market_value"] / aum * 100, 2) if aum > 0 else 0
        h["drift_vs_target"] = round(h["weight"] - h["target_weight"], 2)

    by_ticker = {h["ticker"]: h for h in holdings}

    def _trade(t):
        tid, tk, side, shares, price, trade_off, settle_days, status = t
        h = by_ticker.get(tk)
        gross = shares * price
        return {
            "trade_id": tid,
            "ticker": tk,
            "name": h["name"] if h else tk,
            "side": side,
            "shares": shares,
            "price": price,
            "gross_value": gross,
            "cash_impact": -gross if side == "BUY" else gross,
            "trade_date": add_business_days(TODAY, trade_off).isoformat(),
            "settlement_date": add_business_days(TODAY, trade_off + settle_days).isoformat(),
            "settlement_days": settle_days,
            "cycle": f"T+{settle_days}",
            "status": status,
        }

    pending = [_trade(t) for t in spec.get("pending", [])]
    executed = [_trade(t) for t in spec.get("executed", [])]

    corp = []
    for tk, kind, dps, ex_off, pay_off in spec.get("corp", []):
        h = by_ticker.get(tk)
        shares = h["shares"] if h else 0
        corp.append({
            "ticker": tk,
            "name": h["name"] if h else tk,
            "type": kind,
            "per_share": dps,
            "shares_held": shares,
            "cash_amount": shares * dps,
            "ex_date": add_business_days(TODAY, ex_off).isoformat(),
            "pay_date": add_business_days(TODAY, pay_off).isoformat(),
            "pay_offset_days": pay_off,
        })

    # Minimal expense breakdown (unknown from disclosure)
    ter = spec["meta"].get("expense_ratio")
    expense = {
        "expense_ratio": ter,
        "annual_expense": None,
        "daily_accrual": None,
        "monthly_accrual": None,
        "components": [],
    }

    events = []

    fund = dict(spec["meta"])
    fund["aum"] = aum
    fund["currency"] = "INR"
    fund["as_of"] = TODAY.isoformat()

    return {
        "id": spec["meta"]["fund_id"],
        "fund": fund,
        "holdings": holdings,
        "holdings_by_ticker": by_ticker,
        "aum": aum,
        "cash": {
            "total_cash": cash_total,
            "reserves": round(0.010 * aum) if aum > 0 else 0,
            "reserves_note": "Regulatory + operational minimum cash buffer (not investable).",
            "currency": "INR",
        },
        "pending_trades": pending,
        "executed_trades": executed,
        "corporate_actions": corp,
        "fund_expense": expense,
        "event_calendar": events,
        "unmapped_isins": unmapped_isins,  # Visibility into coverage gaps
    }


FUNDS_V2 = {fid: _build_ds_v2(spec) for fid, spec in FUND_SPECS_V2.items()}
DEFAULT_FUND_ID_V2 = "HDFC-FLEXICAP-DG"


# --------------------------------------------------------------------------- #
# Accessors (matching data.py contract)
# --------------------------------------------------------------------------- #
def list_funds():
    """Return list of funds."""
    return [
        {
            "fund_id": ds["id"],
            "name": ds["fund"]["name"],
            "category": ds["fund"]["category"],
            "amc": ds["fund"]["amc"],
        }
        for ds in FUNDS_V2.values()
    ]


def get_ds(fund_id: str | None) -> dict:
    """Get dataset by fund_id."""
    return FUNDS_V2.get(fund_id or DEFAULT_FUND_ID_V2, FUNDS_V2[DEFAULT_FUND_ID_V2])


def sector_weight(ds, sector):
    """Compute total weight of a sector."""
    return round(sum(h["weight"] for h in ds["holdings"] if h["sector"] == sector), 2)


def group_weight(ds, group):
    """Compute total weight of a business group."""
    return round(sum(h["weight"] for h in ds["holdings"] if h["group"] == group), 2)


def holding(ds, ticker):
    """Get holding by ticker."""
    return ds["holdings_by_ticker"].get(ticker)


def event_for(ds, ticker):
    """Get event for ticker (empty for real data)."""
    for e in ds["event_calendar"]:
        if e["ticker"] == ticker:
            return e
    return None


def _status(used, limit):
    """Status helper for compliance."""
    if used > limit:
        return "BREACH"
    if used >= 0.9 * limit:
        return "WARN"
    return "OK"


COMPLIANCE_LIMITS = {
    "single_issuer_limit": 10.0,
    "group_limit": 20.0,
    "sector_soft_limit": 35.0,
    "min_large_cap_pct": 80.0,
    "max_cash_pct": 20.0,
}


def compliance_utilization(ds):
    """Compute compliance utilization (same structure as data.py)."""
    holdings = ds["holdings"]
    issuers = sorted(holdings, key=lambda h: h["weight"], reverse=True)[:6]
    sectors = sorted(
        {h["sector"] for h in holdings},
        key=lambda s: sector_weight(ds, s),
        reverse=True,
    )[:6]
    groups = sorted(
        {h["group"] for h in holdings},
        key=lambda g: group_weight(ds, g),
        reverse=True,
    )[:5]
    lim = COMPLIANCE_LIMITS
    return {
        "issuers": [
            {
                "entity": h["ticker"],
                "name": h["name"],
                "used": h["weight"],
                "limit": lim["single_issuer_limit"],
                "status": _status(h["weight"], lim["single_issuer_limit"]),
            }
            for h in issuers
        ],
        "sectors": [
            {
                "entity": s,
                "used": sector_weight(ds, s),
                "limit": lim["sector_soft_limit"],
                "status": _status(sector_weight(ds, s), lim["sector_soft_limit"]),
            }
            for s in sectors
        ],
        "groups": [
            {
                "entity": g,
                "used": group_weight(ds, g),
                "limit": lim["group_limit"],
                "status": _status(group_weight(ds, g), lim["group_limit"]),
            }
            for g in groups
        ],
    }
