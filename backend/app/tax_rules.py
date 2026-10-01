"""Indian equity taxation rules for the tax-aware planner/optimizer.

Rates are the real FY 2025-26 statutory values, loaded from
`data/processed/tax/tax_rates.json` (with embedded fallbacks) so a future
budget change is a config edit, not a code change:

  - STCG 20% on gains for lots held < 12 months
  - LTCG 12.5% on gains for lots held >= 12 months (Rs 1.25 lakh annual
    exemption, applied at plan level - it is negligible at crore scale)
  - STT 0.1% of sell value on every delivery sell, plus brokerage/exchange
    charges (~0.033%)
  - Loss lots contribute negative tax (losses offset gains), which is what
    makes tax-loss harvesting attractive to the optimizer.

Real Indian mutual funds are CGT-exempt at fund level (Section 10(23D)); the
capital-gains layer here is a deliberate modeling choice to demonstrate
tax-aware exiting. The STT/transaction charges are real either way.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from . import db

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TAX_RATES_JSON = REPO_ROOT / "data" / "processed" / "tax" / "tax_rates.json"

_DEFAULT_RATES = {
    "financial_year": "2025-26",
    "stcg_rate_pct": 20.0,
    "ltcg_rate_pct": 12.5,
    "ltcg_exemption_inr": 125_000,
    "ltcg_holding_months": 12,
    "stt_sell_pct": 0.10,
    "stamp_duty_buy_pct": 0.015,
    "brokerage_pct": 0.03,
    "exchange_charges_pct": 0.00345,
}


def _load_rates() -> dict:
    # Prefer rates stored in the database (source of truth once init_db.py runs).
    db_rates = db.get_tax_rates()
    if db_rates:
        return {**_DEFAULT_RATES, **{k: v for k, v in db_rates.items() if k in _DEFAULT_RATES}}
    try:
        with open(TAX_RATES_JSON, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        return {**_DEFAULT_RATES, **{k: v for k, v in loaded.items() if k in _DEFAULT_RATES}}
    except (OSError, ValueError):
        return dict(_DEFAULT_RATES)


RATES = _load_rates()

STCG_RATE = RATES["stcg_rate_pct"] / 100
LTCG_RATE = RATES["ltcg_rate_pct"] / 100
LTCG_EXEMPTION_INR = RATES["ltcg_exemption_inr"]
LTCG_HOLDING_MONTHS = RATES["ltcg_holding_months"]
STT_SELL = RATES["stt_sell_pct"] / 100
STAMP_DUTY_BUY = RATES["stamp_duty_buy_pct"] / 100
# Per-rupee friction on every sell regardless of gain/loss.
TXN_COST_SELL = (RATES["stt_sell_pct"] + RATES["brokerage_pct"]
                 + RATES["exchange_charges_pct"]) / 100


def months_between(start: date, end: date) -> int:
    """Whole calendar months from `start` to `end` (day-of-month aware)."""
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day < start.day:
        months -= 1
    return max(months, 0)


def classify_term(acquisition_date: date, as_of: date) -> str:
    """"LTCG" if the lot has been held >= 12 months on `as_of`, else "STCG"."""
    return "LTCG" if months_between(acquisition_date, as_of) >= LTCG_HOLDING_MONTHS else "STCG"


def ltcg_date(acquisition_date: date) -> date:
    """The date on which a lot crosses the 12-month boundary and turns LTCG."""
    month = acquisition_date.month - 1 + LTCG_HOLDING_MONTHS
    year = acquisition_date.year + month // 12
    month = month % 12 + 1
    try:
        return date(year, month, acquisition_date.day)
    except ValueError:  # e.g. Feb 30 -> clamp to end of month
        return date(year, month + 1, 1) if month < 12 else date(year + 1, 1, 1)


def compute_lot_tax(lot: dict, sell_price: float, sell_shares: int, as_of: date) -> dict:
    """Tax of selling `sell_shares` from one lot at `sell_price` on `as_of`.

    lot: {"acquisition_date": date|iso-str, "cost_price": float, ...}
    Returns gain (can be negative), term, cgt (negative for a loss - it
    offsets gains elsewhere in the plan), stt, txn_costs and total_tax.
    """
    acq = lot["acquisition_date"]
    if isinstance(acq, str):
        acq = date.fromisoformat(acq)
    proceeds = sell_price * sell_shares
    gain = (sell_price - lot["cost_price"]) * sell_shares
    term = classify_term(acq, as_of)
    rate = LTCG_RATE if term == "LTCG" else STCG_RATE
    cgt = gain * rate
    stt = proceeds * STT_SELL
    txn = proceeds * TXN_COST_SELL
    return {
        "gain": gain,
        "term": term,
        "cgt": cgt,
        "stt": stt,
        "txn_costs": txn,
        "total_tax": cgt + txn,
    }


def _lot_tax_per_rupee(lot: dict, price: float, as_of: date) -> float:
    """CGT per rupee of proceeds for a lot (excluding flat txn costs)."""
    if not price or price <= 0:
        return 0.0
    acq = lot["acquisition_date"]
    if isinstance(acq, str):
        acq = date.fromisoformat(acq)
    rate = LTCG_RATE if classify_term(acq, as_of) == "LTCG" else STCG_RATE
    return (price - lot["cost_price"]) / price * rate


def effective_tax_rate(lots: list[dict], price: float, as_of: date) -> float:
    """Blended CGT per rupee of proceeds if the position were fully liquidated.

    Used as the per-name linear tax coefficient in the sell LP (partial sells
    consume lots least-tax-first, so this average is conservative for them).
    Negative when the position sits at a net loss - selling it shelters gains.
    """
    if not lots or not price or price <= 0:
        return 0.0
    total_shares = sum(l["quantity"] for l in lots)
    if total_shares <= 0:
        return 0.0
    weighted = sum(_lot_tax_per_rupee(l, price, as_of) * l["quantity"] for l in lots)
    return weighted / total_shares


def attribute_sale(lots: list[dict], sell_price: float, sell_shares: int,
                   as_of: date) -> dict:
    """Attribute a sale across lots least-tax-first ("LTFO") and total the tax.

    Returns a per-order breakdown suitable for the plan response:
    stcg_gain/ltcg_gain, stcg_tax/ltcg_tax, stt, txn_costs, total_tax,
    effective_rate_pct, and the lots consumed.
    """
    remaining = sell_shares
    stcg_gain = ltcg_gain = 0.0
    stt = txn = 0.0
    consumed = []
    ordered = sorted(lots, key=lambda l: _lot_tax_per_rupee(l, sell_price, as_of))
    for lot in ordered:
        if remaining <= 0:
            break
        take = min(remaining, lot["quantity"])
        if take <= 0:
            continue
        acq = lot["acquisition_date"]
        if isinstance(acq, str):
            acq = date.fromisoformat(acq)
        d = compute_lot_tax(lot, sell_price, take, as_of)
        if d["term"] == "LTCG":
            ltcg_gain += d["gain"]
        else:
            stcg_gain += d["gain"]
        stt += d["stt"]
        txn += d["txn_costs"]
        consumed.append({
            "lot_id": lot.get("lot_id"),
            "acquisition_date": acq.isoformat(),
            "shares": take,
            "term": d["term"],
            "gain": round(d["gain"], 2),
        })
        remaining -= take

    stcg_tax = stcg_gain * STCG_RATE
    ltcg_tax = ltcg_gain * LTCG_RATE
    total_tax = stcg_tax + ltcg_tax + txn
    proceeds = sell_price * (sell_shares - max(remaining, 0))
    return {
        "stcg_gain": round(stcg_gain, 2),
        "ltcg_gain": round(ltcg_gain, 2),
        "stcg_tax": round(stcg_tax, 2),
        "ltcg_tax": round(ltcg_tax, 2),
        "stt": round(stt, 2),
        "txn_costs": round(txn, 2),
        "total_tax": round(total_tax, 2),
        "effective_rate_pct": round(total_tax / proceeds * 100, 3) if proceeds else 0.0,
        "lots_consumed": consumed,
        "tax_regime": f"FY{RATES['financial_year']} synthetic PMS-style CGT + real STT/charges",
    }
