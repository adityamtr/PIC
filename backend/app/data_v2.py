"""
Real-data dataset for five mutual funds: HDFC Flexi Cap, ICICI Prudential Large Cap,
SBI Nifty 50 ETF, HDFC Retirement Fund - Equity Plan, and Kotak Large & Mid Cap.

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
from .security_metadata import curate_security_metadata

CRORE = 10_000_000


def add_business_days(start: date, n: int) -> date:
    d, added, step = start, 0, (1 if n >= 0 else -1)
    while added < abs(n):
        d += timedelta(days=step)
        if d.weekday() < 5:
            added += 1
    return d


TODAY = date.today()

COMPLIANCE_LIMITS = {
    "single_issuer_limit": 10.0,
    "group_limit": 20.0,
    "sector_soft_limit": 35.0,
    "min_large_cap_pct": 80.0,
    "max_cash_pct": 20.0,
    "rules": [
        {"code": "SEBI-10PCT", "name": "Single issuer limit", "scope": "issuer", "limit": 10.0,
         "description": "No single company > 10% of NAV (at cost, at time of purchase)."},
        {"code": "GRP-20PCT", "name": "Group exposure limit", "scope": "group", "limit": 20.0,
         "description": "Aggregate exposure to a single business group capped at 20% of NAV."},
        {"code": "SECT-35PCT", "name": "Sector concentration limit", "scope": "sector", "limit": 35.0,
         "description": "Fund-mandated cap of 35% of NAV in any single sector."},
    ],
}

CASH_PCT_BY_FUND = {
    "HDFC-FLEXICAP-DG": 6.0,
    "ICICIPRU-LARGECAP-DG": 3.5,
    "SBI-NIFTY50-ETF-DG": 1.0,
    "HDFC-RETIREMENT-EQUITY-DG": 7.5,
    "KOTAK-LARGEMIDCAP-DG": 5.0,
}

EXPENSE_RATIO_BY_FUND = {
    "HDFC-FLEXICAP-DG": 0.72,
    "ICICIPRU-LARGECAP-DG": 0.68,
    "SBI-NIFTY50-ETF-DG": 0.18,
    "HDFC-RETIREMENT-EQUITY-DG": 0.79,
    "KOTAK-LARGEMIDCAP-DG": 0.74,
}

# Curated lock-in defaults. Real disclosures do not expose lock-in metadata,
# so these values preserve the portfolio's "strategic core" behavior without
# overriding the actual holdings list from the XLSX/CSV feeds.
FUND_LOCK_RULES = {
    "HDFC-FLEXICAP-DG": {
        "POWERGRID": {"locked_pct": 14, "reason": "Strategic utility allocation", "expiry_offset_bdays": 20},
        "LT": {"locked_pct": 12, "reason": "Long-term infra / capex exposure", "expiry_offset_bdays": 18},
        "ITC": {"locked_pct": 8, "reason": "Defensive core holding", "expiry_offset_bdays": 16},
        "BHARTIARTL": {"locked_pct": 6, "reason": "Core telecom holding", "expiry_offset_bdays": 15},
    },
    "ICICIPRU-LARGECAP-DG": {
        "LT": {"locked_pct": 10, "reason": "Infrastructure allocation lock", "expiry_offset_bdays": 18},
        "ICICIBANK": {"locked_pct": 6, "reason": "Core banking holding", "expiry_offset_bdays": 15},
        "RELIANCE": {"locked_pct": 5, "reason": "Large-cap core exposure", "expiry_offset_bdays": 14},
    },
    "SBI-NIFTY50-ETF-DG": {
        "RELIANCE": {"locked_pct": 4, "reason": "Index-core constituent", "expiry_offset_bdays": 12},
        "TCS": {"locked_pct": 3, "reason": "Index-core constituent", "expiry_offset_bdays": 12},
        "INFY": {"locked_pct": 3, "reason": "Index-core constituent", "expiry_offset_bdays": 12},
        "HDFCBANK": {"locked_pct": 3, "reason": "Index-core constituent", "expiry_offset_bdays": 12},
    },
    "HDFC-RETIREMENT-EQUITY-DG": {
        "RELIANCE": {"locked_pct": 8, "reason": "Retirement long-horizon core holding", "expiry_offset_bdays": 18},
        "HDFCBANK": {"locked_pct": 6, "reason": "Defensive quality allocation", "expiry_offset_bdays": 18},
        "ICICIBANK": {"locked_pct": 6, "reason": "Core banking exposure", "expiry_offset_bdays": 16},
        "INFY": {"locked_pct": 4, "reason": "Quality growth allocation", "expiry_offset_bdays": 14},
    },
    "KOTAK-LARGEMIDCAP-DG": {
        "LT": {"locked_pct": 10, "reason": "Capital goods core allocation", "expiry_offset_bdays": 18},
        "SBIN": {"locked_pct": 7, "reason": "Financial plan core holding", "expiry_offset_bdays": 15},
        "MARUTI": {"locked_pct": 6, "reason": "Quality mid-cap allocation", "expiry_offset_bdays": 16},
        "BHARTIARTL": {"locked_pct": 6, "reason": "Telecom core exposure", "expiry_offset_bdays": 16},
    },
}

_EXPENSE_COMPONENTS = [
    {"component": "Investment management & advisory fee", "bps_frac": 0.62},
    {"component": "Administration & operating expenses",  "bps_frac": 0.14},
    {"component": "Registrar & transfer agent (RTA)",     "bps_frac": 0.08},
    {"component": "Custodian & fund accounting",          "bps_frac": 0.05},
    {"component": "Trustee fee",                          "bps_frac": 0.02},
    {"component": "GST & other statutory levies",         "bps_frac": 0.09},
]

# Resolve paths relative to repo root (backend/app/data_v2.py is at <repo>/backend/app/)
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
HDFC_XLSX = REPO_ROOT / "data" / "raw" / "Funds Monthly Portfolio Disclosure(18 funds)" / "current" / "INF179K01UT0_HDFC Flexi Cap Fund.xlsx"
ICICI_XLSX = REPO_ROOT / "data" / "raw" / "Funds Monthly Portfolio Disclosure(18 funds)" / "current" / "INF109K016L0_ICICI Prudential Large Cap Fund.xlsx"
SBI_XLSX = REPO_ROOT / "data" / "raw" / "Funds Monthly Portfolio Disclosure(18 funds)" / "current" / "INF200KA1FS1_SBI Nifty 50 ETF.xlsx"
HDFC_RETIREMENT_XLSX = REPO_ROOT / "data" / "raw" / "Funds Monthly Portfolio Disclosure(18 funds)" / "current" / "INF179KB1MF0_HDFC Retirement Fund - Equity Plan.xlsx"
KOTAK_XLSX = REPO_ROOT / "data" / "raw" / "Funds Monthly Portfolio Disclosure(18 funds)" / "current" / "INF174K01LF9_Kotak Large & Mid Cap Fund.xlsx"
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


def _load_sbi_holdings() -> list[dict]:
    """Load SBI Nifty 50 ETF holdings from XLSX."""
    if not SBI_XLSX.exists():
        raise FileNotFoundError(f"SBI XLSX file not found: {SBI_XLSX}")
    return xlsx_parser.parse_sbi_nifty50_etf(SBI_XLSX)


def _load_hdfc_retirement_holdings() -> list[dict]:
    """Load HDFC Retirement Fund - Equity Plan holdings from XLSX."""
    if not HDFC_RETIREMENT_XLSX.exists():
        raise FileNotFoundError(f"HDFC Retirement XLSX file not found: {HDFC_RETIREMENT_XLSX}")
    return xlsx_parser.parse_hdfc_flexi_cap(HDFC_RETIREMENT_XLSX)


def _load_kotak_holdings() -> list[dict]:
    """Load Kotak Large & Mid Cap holdings from XLSX."""
    if not KOTAK_XLSX.exists():
        raise FileNotFoundError(f"Kotak XLSX file not found: {KOTAK_XLSX}")
    return xlsx_parser.parse_kotak_largemidcap(KOTAK_XLSX)


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
_SBI_HOLDINGS = _load_sbi_holdings()
_HDFC_RETIREMENT_HOLDINGS = _load_hdfc_retirement_holdings()
_KOTAK_HOLDINGS = _load_kotak_holdings()
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
            "fund_manager": "Prashant Jain",
            "inception": "1994-01-01",
            "nav": 2260.5250,
            "expense_ratio": 0.72,
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
            "fund_manager": "Anish Tawakley",
            "inception": "2008-01-01",
            "nav": 117.5600,
            "expense_ratio": 0.68,
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
    "SBI-NIFTY50-ETF-DG": {
        "meta": {
            "fund_id": "SBI-NIFTY50-ETF-DG",
            "name": "SBI Nifty 50 ETF",
            "amc": "SBI Funds Management",
            "category": "Exchange Traded Fund",
            "plan": "Direct - Growth",
            "benchmark": "NIFTY 50 TRI",
            "fund_manager": "SBI Mutual Fund Management Team",
            "inception": "2018-04-04",
            "nav": 254.7696,
            "expense_ratio": 0.18,
            "risk_grade": "High",
        },
        "holdings_list": _SBI_HOLDINGS,
        "pending": [
            ("PT-30101", "RELIANCE", "BUY",  50_000,  3097, 0, 1, "Unsettled"),
            ("PT-30102", "TCS",      "BUY",  30_000,  4150, 0, 1, "Unsettled"),
            ("PT-30103", "INFY",     "BUY",  25_000,  2072, 0, 1, "Unsettled"),
            ("PT-30104", "HDFCBANK", "BUY",  20_000,  1617, 0, 1, "Unsettled"),
            ("PT-30105", "ICICIBANK", "BUY",  15_000,  1196, 0, 1, "Unsettled"),
        ],
        "executed": [
            ("EX-30050", "RELIANCE", "BUY",  100_000, 3097, -3, 1, "Settled"),
            ("EX-30052", "TCS",      "BUY",   60_000, 4150, -2, 1, "Settled"),
            ("EX-30055", "INFY",     "SELL",  40_000, 2072, -2, 1, "Settled"),
            ("EX-30058", "HDFCBANK", "BUY",   30_000, 1617, -1, 1, "Settled"),
        ],
        "corp": [
            ("RELIANCE", "Dividend", 10.0, 3, 10),
            ("TCS",      "Dividend", 12.0, 4, 11),
            ("INFY",     "Dividend", 18.0, 2, 9),
            ("HDFCBANK", "Dividend", 19.5, 8, 16),
        ],
    },
    "HDFC-RETIREMENT-EQUITY-DG": {
        "meta": {
            "fund_id": "HDFC-RETIREMENT-EQUITY-DG",
            "name": "HDFC Retirement Fund - Equity Plan",
            "amc": "HDFC Asset Management Company",
            "category": "Retirement - Equity",
            "plan": "Direct - Growth",
            "benchmark": "NIFTY 500 TRI",
            "fund_manager": "Prashant Jain",
            "inception": "2008-05-01",
            "nav": 55.3060,
            "expense_ratio": 0.79,
            "risk_grade": "Very High",
        },
        "holdings_list": _HDFC_RETIREMENT_HOLDINGS,
        "pending": [
            ("PT-50101", "RELIANCE", "BUY",  60_000,  3097, 0, 1, "Unsettled"),
            ("PT-50102", "ICICIBANK", "BUY",  40_000,  1196, 0, 1, "Unsettled"),
            ("PT-50103", "HDFCBANK", "BUY",  30_000,  1617, 0, 1, "Unsettled"),
            ("PT-50104", "INFY",     "BUY",  25_000,  2072, 0, 1, "Unsettled"),
            ("PT-50105", "TCS",      "BUY",  20_000,  4150, 0, 1, "Unsettled"),
        ],
        "executed": [
            ("EX-50050", "RELIANCE", "BUY",  120_000, 3097, -3, 1, "Settled"),
            ("EX-50052", "ICICIBANK", "BUY",   80_000, 1196, -3, 1, "Settled"),
            ("EX-50055", "HDFCBANK", "SELL",  60_000, 1617, -2, 1, "Settled"),
            ("EX-50058", "INFY",     "BUY",   50_000, 2072, -1, 1, "Settled"),
        ],
        "corp": [
            ("RELIANCE", "Dividend", 10.0, 3, 10),
            ("INFY",     "Dividend", 18.0, 2, 9),
            ("ITC",      "Dividend", 6.5,  5, 12),
            ("HDFCBANK", "Dividend", 19.5, 8, 16),
        ],
    },
    "KOTAK-LARGEMIDCAP-DG": {
        "meta": {
            "fund_id": "KOTAK-LARGEMIDCAP-DG",
            "name": "Kotak Large & Mid Cap Fund",
            "amc": "Kotak Mahindra Asset Management",
            "category": "Equity - Large & Mid Cap",
            "plan": "Direct - Growth",
            "benchmark": "NIFTY LARGE MIDCAP 250 TRI",
            "fund_manager": "Pankaj Tibrewal",
            "inception": "2005-11-01",
            "nav": 406.1990,
            "expense_ratio": 0.74,
            "risk_grade": "Very High",
        },
        "holdings_list": _KOTAK_HOLDINGS,
        "pending": [
            ("PT-50101", "RELIANCE", "BUY",  60_000,  3097, 0, 1, "Unsettled"),
            ("PT-50102", "LT",       "BUY",  40_000,  3720, 0, 1, "Unsettled"),
            ("PT-50103", "SBIN",     "BUY",  30_000,  826,  0, 1, "Unsettled"),
            ("PT-50104", "BHARTIARTL","BUY",  25_000,  1689, 0, 1, "Unsettled"),
            ("PT-50105", "MARUTI",   "BUY",  20_000, 13500, 0, 1, "Unsettled"),
        ],
        "executed": [
            ("EX-50050", "RELIANCE", "BUY",  120_000, 3097, -3, 1, "Settled"),
            ("EX-50052", "LT",       "BUY",   80_000, 3720, -2, 1, "Settled"),
            ("EX-50055", "SBIN",     "SELL",  50_000,  826, -2, 1, "Settled"),
            ("EX-50058", "MARUTI",   "BUY",   30_000,13500, -1, 1, "Settled"),
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
    """Build dataset from real holdings + prices, with curated defaults for fields not present in raw feed."""
    fund_holdings = spec["holdings_list"]
    fund_id = spec["meta"]["fund_id"]

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
            # Disclosures do not provide a reliable business-group field.
            # Use issuer-level fallback rather than incorrectly grouping every
            # security in an industry under one business group.
            "group": ticker,
            "group_source": "issuer_fallback",
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
        holdings[-1].update(curate_security_metadata(
            ticker, industry, market_value * 100_000, base_price, TODAY,
        ))

    equity = sum(h["market_value"] for h in holdings)
    cash_pct = CASH_PCT_BY_FUND.get(fund_id, 5.0)
    cash_total = round(equity * (cash_pct / 100), 2) if equity > 0 else 0
    aum = equity + cash_total

    # Some disclosure layouts expose unrelated numeric columns near %NAV.
    # Replace impossible or missing target percentages with the observed
    # market-value weight so rebalance plans remain dimensionally realistic.
    for h in holdings:
        if h["target_weight"] <= 0 or h["target_weight"] > 100:
            h["target_weight"] = round(h["market_value"] / equity * 100, 4) if equity else 0
    target_total = sum(h["target_weight"] for h in holdings)
    if target_total < 50 or target_total > 105:
        for h in holdings:
            h["target_weight"] = round(h["market_value"] / equity * 100, 4) if equity else 0

    lock_rules = FUND_LOCK_RULES.get(fund_id, {})
    for h in holdings:
        lock_cfg = lock_rules.get(h["ticker"], {})
        lock_pct = lock_cfg.get("locked_pct", 0)
        expiry_offset = lock_cfg.get("expiry_offset_bdays", 20)
        locked = round(h["shares"] * lock_pct / 100) if lock_pct > 0 else 0
        h["locked_shares"] = locked
        h["sellable_shares"] = max(h["shares"] - locked, 0)
        h["lock_in_expiry"] = add_business_days(TODAY, expiry_offset).isoformat() if lock_pct > 0 else None
        h["lock_in_reason"] = lock_cfg.get("reason")
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
            "status": "declared", "confidence": 0.95, "source": "curated_demo",
        })

    ter = spec["meta"].get("expense_ratio")
    if ter is None:
        ter = EXPENSE_RATIO_BY_FUND.get(fund_id, 0.75)
    annual = aum * ter / 100
    expense = {
        "expense_ratio": ter,
        "annual_expense": annual,
        "daily_accrual": annual / 365,
        "monthly_accrual": annual / 12,
        "components": [
            {"component": c["component"], "bps": round(ter * 100 * c["bps_frac"]),
             "annual_amount": annual * c["bps_frac"]}
            for c in _EXPENSE_COMPONENTS
        ],
    }

    # Real-data feed contains no event calendar; fill a consistent event set by
    # sector/portfolio behavior so downstream screens still render meaningful data.
    events = []
    event_map = {
        "INFY": ("Q results / dividend ex-date", 2),
        "RELIANCE": ("Dividend ex-date", 3),
        "ITC": ("Dividend ex-date", 5),
        "TCS": ("Q results", 6),
        "HDFCBANK": ("Dividend ex-date", 8),
        "COALINDIA": ("Dividend ex-date", 2),
        "MARUTI": ("Q results", 4),
        "MPHASIS": ("Q results", 3),
        "POWERGRID": ("Dividend ex-date", 6),
        "LT": ("Q results / dividend ex-date", 7),
        "BHARTIARTL": ("Q results", 4),
        "SBIN": ("Quarterly results", 5),
        "ICICIBANK": ("Quarterly results", 5),
        "AXISBANK": ("Quarterly results", 4),
    }
    for tk, (ev, offset) in event_map.items():
        if tk in by_ticker:
            events.append({
                "ticker": tk,
                "event": ev,
                "event_date": add_business_days(TODAY, offset).isoformat(),
                "days_out": offset,
            })

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
        "unmapped_isins": unmapped_isins,
        "restricted_securities": [], "watchlist_securities": [],
        "policy_data_as_of": TODAY.isoformat(),
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
    "rules": [
        {"code": "SEBI-10PCT", "name": "Single issuer limit", "scope": "issuer", "limit": 10.0,
         "description": "No single company > 10% of NAV at the position level."},
        {"code": "GRP-20PCT", "name": "Group exposure limit", "scope": "group", "limit": 20.0,
         "description": "Aggregate exposure to a single business group capped at 20% of NAV."},
        {"code": "SECT-35PCT", "name": "Sector concentration limit", "scope": "sector", "limit": 35.0,
         "description": "Portfolio sector exposure should remain under the soft cap for a balanced risk profile."},
    ],
}

FUND_COMPLIANCE_LIMITS = {
    "HDFC-FLEXICAP-DG": {
        "single_issuer_limit": 10.0,
        "group_limit": 20.0,
        "sector_soft_limit": 35.0,
        "min_large_cap_pct": 65.0,
        "max_cash_pct": 15.0,
        "rules": [
            {"code": "SEBI-10PCT", "name": "Single issuer limit", "scope": "issuer", "limit": 10.0,
             "description": "Flexi-cap portfolio keeps single-name risk controlled while retaining quality growth holdings."},
            {"code": "GRP-20PCT", "name": "Group exposure limit", "scope": "group", "limit": 20.0,
             "description": "Business-group concentration remains capped for a diversified flexi-cap book."},
            {"code": "SECT-35PCT", "name": "Sector concentration limit", "scope": "sector", "limit": 35.0,
             "description": "Sector concentration is capped to avoid large cyclical concentration in the flexi-cap strategy."},
        ],
    },
    "ICICIPRU-LARGECAP-DG": {
        "single_issuer_limit": 10.0,
        "group_limit": 20.0,
        "sector_soft_limit": 35.0,
        "min_large_cap_pct": 80.0,
        "max_cash_pct": 12.0,
        "rules": [
            {"code": "SEBI-10PCT", "name": "Single issuer limit", "scope": "issuer", "limit": 10.0,
             "description": "Large-cap mandate keeps a strict cap on individual stock concentration."},
            {"code": "GRP-20PCT", "name": "Group exposure limit", "scope": "group", "limit": 20.0,
             "description": "Business-group exposure is capped even in a benchmark-led fund."},
            {"code": "SECT-35PCT", "name": "Sector concentration limit", "scope": "sector", "limit": 35.0,
             "description": "Sector caps preserve a balanced large-cap risk profile."},
        ],
    },
    "SBI-NIFTY50-ETF-DG": {
        "single_issuer_limit": 13.0,
        "group_limit": 18.0,
        "sector_soft_limit": 30.0,
        "min_large_cap_pct": 100.0,
        "max_cash_pct": 5.0,
        "rules": [
            {"code": "ETF-13PCT", "name": "Constituent cap", "scope": "issuer", "limit": 13.0,
             "description": "Index ETF remains benchmark-aligned, with no single constituent dominating beyond normal index weights."},
            {"code": "ETF-GRP-18PCT", "name": "Group concentration", "scope": "group", "limit": 18.0,
             "description": "ETF is kept diversified across business groups, with no single group dominating the portfolio."},
            {"code": "ETF-SECT-30PCT", "name": "Sector soft cap", "scope": "sector", "limit": 30.0,
             "description": "The benchmark is large-cap skewed and sector exposures are kept near index alignment."},
        ],
    },
    "HDFC-RETIREMENT-EQUITY-DG": {
        "single_issuer_limit": 10.0,
        "group_limit": 18.0,
        "sector_soft_limit": 30.0,
        "min_large_cap_pct": 75.0,
        "max_cash_pct": 12.0,
        "rules": [
            {"code": "SEBI-10PCT", "name": "Single issuer limit", "scope": "issuer", "limit": 10.0,
             "description": "Retirement equity allocation stays concentrated in high-quality, durable businesses without over-allocating to any single stock."},
            {"code": "GRP-18PCT", "name": "Group exposure limit", "scope": "group", "limit": 18.0,
             "description": "Group concentration is kept lower than a standard equity fund to support longer-horizon stability."},
            {"code": "SECT-30PCT", "name": "Sector concentration limit", "scope": "sector", "limit": 30.0,
             "description": "The retirement strategy avoids sector-heavy concentration to reduce timing risk."},
        ],
    },
    "KOTAK-LARGEMIDCAP-DG": {
        "single_issuer_limit": 10.0,
        "group_limit": 20.0,
        "sector_soft_limit": 35.0,
        "min_large_cap_pct": 70.0,
        "max_cash_pct": 14.0,
        "rules": [
            {"code": "SEBI-10PCT", "name": "Single issuer limit", "scope": "issuer", "limit": 10.0,
             "description": "Large & mid-cap strategy controls single-stock risk while allowing mid-cap participation."},
            {"code": "GRP-20PCT", "name": "Group exposure limit", "scope": "group", "limit": 20.0,
             "description": "The portfolio keeps diversified business-group exposure to balance growth bias."},
            {"code": "SECT-35PCT", "name": "Sector concentration limit", "scope": "sector", "limit": 35.0,
             "description": "Sector concentration is capped while giving room to the qualitative large-cap and mid-cap mix."},
        ],
    },
}


def get_fund_compliance_limits(fund_id: str | None = None):
    """Return compliance limits tuned to the fund's mandate while preserving raw holdings."""
    fund_key = fund_id or DEFAULT_FUND_ID_V2
    return FUND_COMPLIANCE_LIMITS.get(fund_key, COMPLIANCE_LIMITS)


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
    lim = get_fund_compliance_limits(ds["id"])
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
