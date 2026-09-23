"""
Synthetic dataset for the PIC trade-plan demo — now multi-fund.

Everything here is fabricated for demonstration only. Two popular Indian funds
are modelled, each with its own holdings, cash, trades, corporate actions and
expense structure:

  - HDFC Top 100 Fund        (large-cap, broad)
  - Parag Parikh Flexi Cap   (flexi-cap, concentrated, cash-heavy)

Each fund is built into a self-contained "dataset" (ds) dict. The planner and
API operate on a ds selected by fund_id, so adding more funds later is just a
matter of adding another spec.

Numbers are illustrative, not real. Replace this module with live feeds later.
"""

from __future__ import annotations

from datetime import date, timedelta

CRORE = 10_000_000


def add_business_days(start: date, n: int) -> date:
    d, added, step = start, 0, (1 if n >= 0 else -1)
    while added < abs(n):
        d += timedelta(days=step)
        if d.weekday() < 5:
            added += 1
    return d


TODAY = date.today()


# --------------------------------------------------------------------------- #
# Shared reference data (market-wide, fund-independent)
# --------------------------------------------------------------------------- #
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

UNIVERSE = [
    {"ticker": "INFY",    "name": "Infosys Ltd",               "sector": "Information Technology", "price": 2072,  "adv_cr": 1450},
    {"ticker": "TCS",     "name": "Tata Consultancy Services", "sector": "Information Technology", "price": 4469,  "adv_cr": 980},
    {"ticker": "HCLTECH", "name": "HCL Technologies Ltd",      "sector": "Information Technology", "price": 1782,  "adv_cr": 720},
    {"ticker": "LTIM",    "name": "LTIMindtree Ltd",           "sector": "Information Technology", "price": 5900,  "adv_cr": 260},
    {"ticker": "TECHM",   "name": "Tech Mahindra Ltd",         "sector": "Information Technology", "price": 1650,  "adv_cr": 540},
    {"ticker": "HDFCBANK","name": "HDFC Bank Ltd",             "sector": "Financial Services",     "price": 1617,  "adv_cr": 1850},
    {"ticker": "ICICIBANK","name": "ICICI Bank Ltd",           "sector": "Financial Services",     "price": 1196,  "adv_cr": 1620},
    {"ticker": "AXISBANK","name": "Axis Bank Ltd",             "sector": "Financial Services",     "price": 1048,  "adv_cr": 900},
    {"ticker": "RELIANCE","name": "Reliance Industries Ltd",   "sector": "Energy",                 "price": 3097,  "adv_cr": 2100},
    {"ticker": "NTPC",    "name": "NTPC Ltd",                  "sector": "Utilities",              "price": 371,   "adv_cr": 640},
    {"ticker": "ITC",     "name": "ITC Ltd",                   "sector": "FMCG",                   "price": 451,   "adv_cr": 780},
    {"ticker": "MARUTI",  "name": "Maruti Suzuki India Ltd",   "sector": "Automobile",             "price": 13500, "adv_cr": 420},
    {"ticker": "SUNPHARMA","name": "Sun Pharmaceutical Ind",   "sector": "Healthcare",             "price": 1869,  "adv_cr": 480},
    {"ticker": "CIPLA",   "name": "Cipla Ltd",                 "sector": "Healthcare",             "price": 1550,  "adv_cr": 360},
]

BUY_ALLOCATION = {
    "Information Technology": {"INFY": 0.35, "TCS": 0.30, "HCLTECH": 0.15, "LTIM": 0.12, "TECHM": 0.08},
    "Financial Services":     {"HDFCBANK": 0.40, "ICICIBANK": 0.35, "AXISBANK": 0.25},
    "Energy":                 {"RELIANCE": 0.70, "NTPC": 0.30},
    "FMCG":                   {"ITC": 1.0},
    "Automobile":             {"MARUTI": 1.0},
    "Healthcare":             {"SUNPHARMA": 0.6, "CIPLA": 0.4},
}


def universe_entry(ticker):
    for u in UNIVERSE:
        if u["ticker"] == ticker:
            return u
    return None


# --------------------------------------------------------------------------- #
# Fund specifications
#   holdings tuple: (ticker, name, sector, group, base_price, target_wt%,
#                    drift%, locked_pct, lock_expiry_offset_bdays, lock_reason)
#   trade tuple:    (id, ticker, side, shares, price, trade_offset, settle_days, status)
#   corp tuple:     (ticker, type, per_share, ex_offset, pay_offset)
# --------------------------------------------------------------------------- #
FUND_SPECS = {
    "HDFC-TOP100-DG": {
        "meta": {
            "fund_id": "HDFC-TOP100-DG", "name": "HDFC Top 100 Fund",
            "amc": "HDFC Asset Management Company", "category": "Equity - Large Cap",
            "plan": "Direct - Growth", "benchmark": "NIFTY 100 TRI",
            "fund_manager": "Rahul Baijal", "inception": "1996-10-11",
            "nav": 1024.56, "expense_ratio": 1.05, "risk_grade": "Very High",
        },
        "base_aum": 32500 * CRORE,
        "cash_total": 1200 * CRORE,
        "holdings": [
            ("HDFCBANK",   "HDFC Bank Ltd",              "Financial Services",    "HDFC Group",        1650,  9.5, -2, 0,  None, None),
            ("ICICIBANK",  "ICICI Bank Ltd",             "Financial Services",    "ICICI Group",       1150,  8.1, +4, 0,  None, None),
            ("AXISBANK",   "Axis Bank Ltd",              "Financial Services",    "Axis Group",        1080,  4.3, -3, 0,  None, None),
            ("KOTAKBANK",  "Kotak Mahindra Bank Ltd",    "Financial Services",    "Kotak Group",       1750,  3.0, +1, 0,  None, None),
            ("SBIN",       "State Bank of India",        "Financial Services",    "SBI Group",          780,  3.5, +6, 0,  None, None),
            ("BAJFINANCE", "Bajaj Finance Ltd",          "Financial Services",    "Bajaj Group",       6800,  2.4, -5, 0,  None, None),
            ("BAJAJFINSV", "Bajaj Finserv Ltd",          "Financial Services",    "Bajaj Group",       1650,  1.6, -4, 0,  None, None),
            ("INFY",       "Infosys Ltd",                "Information Technology", "Infosys",           1850,  6.5, +12, 0,  None, None),
            ("TCS",        "Tata Consultancy Services",  "Information Technology", "Tata Group",        4100,  4.2, +9, 0,  None, None),
            ("HCLTECH",    "HCL Technologies Ltd",       "Information Technology", "HCL Group",         1620,  2.3, +10, 0,  None, None),
            ("WIPRO",      "Wipro Ltd",                  "Information Technology", "Wipro",              550,  1.4, +7, 0,  None, None),
            ("RELIANCE",   "Reliance Industries Ltd",    "Energy",                "Reliance Group",    2950,  8.3, +5, 0,  None, None),
            ("ONGC",       "Oil & Natural Gas Corp",     "Energy",                "PSU",                270,  1.5, -6, 0,  None, None),
            ("COALINDIA",  "Coal India Ltd",             "Energy",                "PSU",                480,  1.3, -8, 40, 35, "PSU strategic-holding lock-in"),
            ("NTPC",       "NTPC Ltd",                   "Utilities",             "PSU",                360,  2.0, +3, 0,  None, None),
            ("POWERGRID",  "Power Grid Corp of India",   "Utilities",             "PSU",                320,  1.6, +2, 0,  None, None),
            ("ITC",        "ITC Ltd",                    "FMCG",                  "ITC",                460,  4.1, -2, 0,  None, None),
            ("HINDUNILVR", "Hindustan Unilever Ltd",     "FMCG",                  "Unilever",          2450,  3.4, -4, 0,  None, None),
            ("NESTLEIND",  "Nestle India Ltd",           "FMCG",                  "Nestle",            2500,  1.5, -3, 0,  None, None),
            ("MARUTI",     "Maruti Suzuki India Ltd",    "Automobile",            "Suzuki",           12500,  2.6, +8, 0,  None, None),
            ("M&M",        "Mahindra & Mahindra Ltd",    "Automobile",            "Mahindra Group",    2850,  2.2, +11, 0,  None, None),
            ("TATAMOTORS", "Tata Motors Ltd",            "Automobile",            "Tata Group",         980,  1.5, -7, 0,  None, None),
            ("BHARTIARTL", "Bharti Airtel Ltd",          "Telecom",               "Bharti Group",      1550,  4.0, +9, 0,  None, None),
            ("LT",         "Larsen & Toubro Ltd",        "Capital Goods",         "L&T Group",         3650,  4.5, +6, 20, 12, "Board-approved pledge lock-in"),
            ("SUNPHARMA",  "Sun Pharmaceutical Ind",     "Healthcare",            "Sun Pharma",        1780,  1.8, +5, 0,  None, None),
            ("DRREDDY",    "Dr Reddy's Laboratories",    "Healthcare",            "Dr Reddy's",        1280,  1.2, -3, 0,  None, None),
            ("TATASTEEL",  "Tata Steel Ltd",             "Metals & Mining",       "Tata Group",         150,  1.4, -10, 0,  None, None),
            ("ULTRACEMCO", "UltraTech Cement Ltd",       "Construction Materials","Aditya Birla Group",11200, 1.8, +4, 0,  None, None),
            ("GRASIM",     "Grasim Industries Ltd",      "Construction Materials","Aditya Birla Group", 2450, 1.1, +2, 0,  None, None),
            ("TITAN",      "Titan Company Ltd",          "Consumer Durables",     "Tata Group",        3550,  2.0, -6, 0,  None, None),
            ("ASIANPAINT", "Asian Paints Ltd",           "Consumer Durables",     "Asian Paints",      2900,  1.6, -8, 0,  None, None),
        ],
        "pending": [
            ("PT-10231", "INFY",      "BUY",  40_000,  2072, 0, 1, "Unsettled"),
            ("PT-10232", "TATASTEEL", "SELL", 300_000, 135,  0, 1, "Unsettled"),
            ("PT-10233", "RELIANCE",  "BUY",  25_000,  3097, -1, 2, "Unsettled"),
            ("PT-10234", "WIPRO",     "SELL", 100_000, 588,  0, 1, "Unsettled"),
            ("PT-10235", "HDFCBANK",  "BUY",  20_000,  1617, -1, 2, "Unsettled"),
        ],
        "executed": [
            ("EX-10188", "ICICIBANK", "BUY",  60_000,  1196, -3, 1, "Settled"),
            ("EX-10190", "SBIN",      "BUY",  120_000, 826,  -3, 1, "Settled"),
            ("EX-10193", "ONGC",      "SELL", 200_000, 253,  -2, 1, "Settled"),
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

    "PPFAS-FLEXI-DG": {
        "meta": {
            "fund_id": "PPFAS-FLEXI-DG", "name": "Parag Parikh Flexi Cap Fund",
            "amc": "PPFAS Mutual Fund", "category": "Equity - Flexi Cap",
            "plan": "Direct - Growth", "benchmark": "NIFTY 500 TRI",
            "fund_manager": "Rajeev Thakkar", "inception": "2013-05-24",
            "nav": 82.34, "expense_ratio": 0.63, "risk_grade": "Very High",
        },
        "base_aum": 90000 * CRORE,
        "cash_total": 13500 * CRORE,   # PPFAS is known for holding higher cash
        "holdings": [
            ("HDFCBANK",   "HDFC Bank Ltd",                 "Financial Services", "HDFC Group",     1650,  9.0, -1, 0,  None, None),
            ("BAJAJHLDNG", "Bajaj Holdings & Investment",   "Financial Services", "Bajaj Group",   10500,  8.0, +6, 0,  None, None),
            ("POWERGRID",  "Power Grid Corp of India",      "Utilities",          "PSU",             320,  7.0, +3, 0,  None, None),
            ("ITC",        "ITC Ltd",                       "FMCG",               "ITC",             460,  7.0, -2, 0,  None, None),
            ("COALINDIA",  "Coal India Ltd",                "Energy",             "PSU",             480,  6.5, -5, 30, 40, "PSU strategic-holding lock-in"),
            ("ICICIBANK",  "ICICI Bank Ltd",                "Financial Services", "ICICI Group",    1150,  6.0, +4, 0,  None, None),
            ("HCLTECH",    "HCL Technologies Ltd",          "Information Technology", "HCL Group",   1620,  5.5, +9, 0,  None, None),
            ("MARUTI",     "Maruti Suzuki India Ltd",       "Automobile",         "Suzuki",        12500,  5.0, +7, 0,  None, None),
            ("KOTAKBANK",  "Kotak Mahindra Bank Ltd",       "Financial Services", "Kotak Group",    1750,  4.5, +1, 0,  None, None),
            ("AXISBANK",   "Axis Bank Ltd",                 "Financial Services", "Axis Group",     1080,  4.5, -3, 0,  None, None),
            ("INFY",       "Infosys Ltd",                   "Information Technology", "Infosys",     1850,  4.5, +12, 0,  None, None),
            ("CIPLA",      "Cipla Ltd",                     "Healthcare",         "Cipla",          1450,  4.0, +5, 0,  None, None),
            ("MPHASIS",    "Mphasis Ltd",                   "Information Technology", "Blackstone",  2700,  3.5, +8, 0,  None, None),
            ("MOTILALOFS", "Motilal Oswal Financial Serv",  "Financial Services", "Motilal Oswal",   760,  3.0, +14, 0,  None, None),
        ],
        "pending": [
            ("PT-22101", "HDFCBANK", "BUY",  90_000,  1617, 0, 1, "Unsettled"),
            ("PT-22102", "COALINDIA","SELL", 400_000, 456,  0, 1, "Unsettled"),
            ("PT-22103", "MARUTI",   "BUY",  6_000,   13500, -1, 2, "Unsettled"),
            ("PT-22104", "MPHASIS",  "BUY",  50_000,  2916, 0, 1, "Unsettled"),
        ],
        "executed": [
            ("EX-22050", "ITC",       "BUY",  500_000, 451,  -3, 1, "Settled"),
            ("EX-22052", "POWERGRID", "BUY",  800_000, 330,  -2, 1, "Settled"),
            ("EX-22055", "INFY",      "SELL", 60_000,  2072, -2, 1, "Settled"),
            ("EX-22058", "AXISBANK",  "BUY",  120_000, 1048, -1, 1, "Settled"),
        ],
        "corp": [
            ("COALINDIA",  "Dividend", 15.5, 2, 8),
            ("ITC",        "Dividend", 6.5,  4, 11),
            ("POWERGRID",  "Dividend", 4.5,  6, 13),
            ("BAJAJHLDNG", "Dividend", 65.0, 7, 15),
        ],
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

_EVENTS_BY_TICKER = {
    "INFY":     ("Q results / dividend ex-date", 2),
    "RELIANCE": ("Dividend ex-date",             3),
    "ITC":      ("Dividend ex-date",             5),
    "TCS":      ("Q results",                    6),
    "HDFCBANK": ("Dividend ex-date",             8),
    "COALINDIA":("Dividend ex-date",             2),
    "MARUTI":   ("Q results",                    4),
    "MPHASIS":  ("Q results",                    3),
    "POWERGRID":("Dividend ex-date",             6),
}


# --------------------------------------------------------------------------- #
# Builder: turn a spec into a fully-computed dataset (ds)
# --------------------------------------------------------------------------- #
def _build_ds(spec: dict) -> dict:
    base_aum = spec["base_aum"]
    cash_total = spec["cash_total"]

    holdings = []
    for tk, name, sector, group, base_price, tw, drift, lock_pct, lock_off, lock_reason in spec["holdings"]:
        shares = round(tw / 100 * base_aum / base_price)
        price = round(base_price * (1 + drift / 100), 2)
        mv = shares * price
        locked = round(shares * lock_pct / 100)
        holdings.append({
            "ticker": tk, "name": name, "sector": sector, "group": group,
            "price": price, "base_price": base_price, "shares": shares,
            "market_value": mv, "target_weight": tw, "locked_shares": locked,
            "sellable_shares": shares - locked,
            "lock_in_expiry": add_business_days(TODAY, lock_off).isoformat() if lock_off else None,
            "lock_in_reason": lock_reason,
        })

    equity = sum(h["market_value"] for h in holdings)
    aum = equity + cash_total
    for h in holdings:
        h["weight"] = round(h["market_value"] / aum * 100, 2)
        h["drift_vs_target"] = round(h["weight"] - h["target_weight"], 2)

    by_ticker = {h["ticker"]: h for h in holdings}

    def _trade(t):
        tid, tk, side, shares, price, trade_off, settle_days, status = t
        h = by_ticker.get(tk)
        gross = shares * price
        return {
            "trade_id": tid, "ticker": tk, "name": h["name"] if h else tk,
            "side": side, "shares": shares, "price": price, "gross_value": gross,
            "cash_impact": -gross if side == "BUY" else gross,
            "trade_date": add_business_days(TODAY, trade_off).isoformat(),
            "settlement_date": add_business_days(TODAY, trade_off + settle_days).isoformat(),
            "settlement_days": settle_days, "cycle": f"T+{settle_days}", "status": status,
        }

    pending = [_trade(t) for t in spec["pending"]]
    executed = [_trade(t) for t in spec["executed"]]

    corp = []
    for tk, kind, dps, ex_off, pay_off in spec["corp"]:
        h = by_ticker.get(tk)
        shares = h["shares"] if h else 0
        corp.append({
            "ticker": tk, "name": h["name"] if h else tk, "type": kind,
            "per_share": dps, "shares_held": shares, "cash_amount": shares * dps,
            "ex_date": add_business_days(TODAY, ex_off).isoformat(),
            "pay_date": add_business_days(TODAY, pay_off).isoformat(),
            "pay_offset_days": pay_off,
        })

    ter = spec["meta"]["expense_ratio"]
    annual = aum * ter / 100
    expense = {
        "expense_ratio": ter, "annual_expense": annual,
        "daily_accrual": annual / 365, "monthly_accrual": annual / 12,
        "components": [
            {"component": c["component"], "bps": round(ter * 100 * c["bps_frac"]),
             "annual_amount": annual * c["bps_frac"]}
            for c in _EXPENSE_COMPONENTS
        ],
    }

    events = [
        {"ticker": tk, "event": ev, "event_date": add_business_days(TODAY, off).isoformat(), "days_out": off}
        for tk, (ev, off) in _EVENTS_BY_TICKER.items() if tk in by_ticker
    ]

    fund = dict(spec["meta"])
    fund["aum"] = aum
    fund["currency"] = "INR"
    fund["as_of"] = TODAY.isoformat()

    return {
        "id": spec["meta"]["fund_id"], "fund": fund, "holdings": holdings,
        "holdings_by_ticker": by_ticker, "aum": aum,
        "cash": {"total_cash": cash_total, "reserves": round(0.010 * aum),
                 "reserves_note": "Regulatory + operational minimum cash buffer (not investable).",
                 "currency": "INR"},
        "pending_trades": pending, "executed_trades": executed,
        "corporate_actions": corp, "fund_expense": expense, "event_calendar": events,
    }


FUNDS = {fid: _build_ds(spec) for fid, spec in FUND_SPECS.items()}
DEFAULT_FUND_ID = "HDFC-TOP100-DG"


# --------------------------------------------------------------------------- #
# Accessors (ds-based)
# --------------------------------------------------------------------------- #
def list_funds():
    return [{"fund_id": ds["id"], "name": ds["fund"]["name"],
             "category": ds["fund"]["category"], "amc": ds["fund"]["amc"]}
            for ds in FUNDS.values()]


def get_ds(fund_id: str | None) -> dict:
    return FUNDS.get(fund_id or DEFAULT_FUND_ID, FUNDS[DEFAULT_FUND_ID])


def sector_weight(ds, sector):
    return round(sum(h["weight"] for h in ds["holdings"] if h["sector"] == sector), 2)


def group_weight(ds, group):
    return round(sum(h["weight"] for h in ds["holdings"] if h["group"] == group), 2)


def holding(ds, ticker):
    return ds["holdings_by_ticker"].get(ticker)


def event_for(ds, ticker):
    for e in ds["event_calendar"]:
        if e["ticker"] == ticker:
            return e
    return None


def _status(used, limit):
    if used > limit:
        return "BREACH"
    if used >= 0.9 * limit:
        return "WARN"
    return "OK"


def compliance_utilization(ds):
    holdings = ds["holdings"]
    issuers = sorted(holdings, key=lambda h: h["weight"], reverse=True)[:6]
    sectors = sorted({h["sector"] for h in holdings}, key=lambda s: sector_weight(ds, s), reverse=True)[:6]
    groups = sorted({h["group"] for h in holdings}, key=lambda g: group_weight(ds, g), reverse=True)[:5]
    lim = COMPLIANCE_LIMITS
    return {
        "issuers": [{"entity": h["ticker"], "name": h["name"], "used": h["weight"],
                     "limit": lim["single_issuer_limit"],
                     "status": _status(h["weight"], lim["single_issuer_limit"])} for h in issuers],
        "sectors": [{"entity": s, "used": sector_weight(ds, s), "limit": lim["sector_soft_limit"],
                     "status": _status(sector_weight(ds, s), lim["sector_soft_limit"])} for s in sectors],
        "groups": [{"entity": g, "used": group_weight(ds, g), "limit": lim["group_limit"],
                    "status": _status(group_weight(ds, g), lim["group_limit"])} for g in groups],
    }
