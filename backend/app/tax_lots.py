"""Synthetic tax-lot data for the tax-aware planner.

Fund disclosures give quantity / market value / %NAV only - never purchase
history - and no external source exists for a fund's private lots. So lots are
synthesized, but anchored to reality: each lot's cost price is the stock's
REAL monthly close (from data/processed/final/stock_macro_monthly_target.csv)
on its synthetic acquisition date, so unrealized gains reflect actual price
history. Generation is deterministic (seeded by ISIN) and reproducible.

Rules baked in per holding:
  - 2-5 lots; at least one LTCG lot (13-36 months old) and, where the position
    is large enough, at least one STCG lot (1-11 months old).
  - ~18% of names are "loss candidates": one lot is placed at the month with
    the highest close in the past 36 months, maximizing the chance of a
    genuine (real-price) loss lot for tax-loss harvesting demos.

The generated lots are persisted to data/processed/tax/tax_lots.csv via
`python -m app.tax_lots` so they can be inspected; at startup `data_v2` calls
`attach_tax_data`, which prefers the persisted file and falls back to the
same deterministic generator (identical output) when a holding is missing.
"""

from __future__ import annotations

import csv
import hashlib
import random
from datetime import date
from pathlib import Path

from . import tax_rules
from .tax_rules import (LTCG_HOLDING_MONTHS, TXN_COST_SELL, attribute_sale,
                        classify_term, effective_tax_rate, ltcg_date)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TAX_DIR = REPO_ROOT / "data" / "processed" / "tax"
TAX_LOTS_CSV = TAX_DIR / "tax_lots.csv"
PRICES_CSV = REPO_ROOT / "data" / "processed" / "final" / "stock_macro_monthly_target.csv"

_LOSS_CANDIDATE_FRACTION = 0.18
_MAX_MONTHS_BACK = 36

_price_history_cache: dict | None = None
_persisted_cache: dict | None = None


def _seed_for(isin: str) -> int:
    return int(hashlib.sha256(isin.encode("utf-8")).hexdigest()[:12], 16)


def _shift_months(d: date, months_back: int) -> date:
    month = d.month - 1 - months_back
    year = d.year + month // 12
    month = month % 12 + 1
    return date(year, month, 1)


def _price_history() -> dict:
    """Lazy-loaded {isin: sorted [(iso_date, close)]} from the macro dataset.

    Only needed when generating lots (script run, or fallback for a holding
    missing from the persisted CSV); the normal serving path never loads it.
    """
    global _price_history_cache
    if _price_history_cache is not None:
        return _price_history_cache
    history: dict[str, list] = {}
    if PRICES_CSV.exists():
        with open(PRICES_CSV, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                isin = row.get("isin")
                d = row.get("date")
                close = row.get("monthly_close") or row.get("monthly_adj_close")
                if not isin or not d or not close:
                    continue
                try:
                    history.setdefault(isin, []).append((d, float(close)))
                except (ValueError, TypeError):
                    continue
        for isin in history:
            history[isin].sort()
    _price_history_cache = history
    return history


def _close_near(isin: str, target: date) -> tuple[date, float] | None:
    """The real (date, close) observation nearest at-or-before `target`."""
    series = _price_history().get(isin)
    if not series:
        return None
    target_iso = target.isoformat()
    best = None
    for d, close in series:
        if d <= target_iso:
            best = (d, close)
        else:
            break
    if best is None:  # stock listed after target: use its earliest observation
        best = series[0]
    return date.fromisoformat(best[0]), best[1]


def _max_close_month(isin: str, as_of: date) -> tuple[date, float] | None:
    """The real (date, close) with the highest close in the past 36 months."""
    series = _price_history().get(isin)
    if not series:
        return None
    lo = _shift_months(as_of, _MAX_MONTHS_BACK).isoformat()
    hi = as_of.isoformat()
    window = [(d, c) for d, c in series if lo <= d < hi]
    if not window:
        return None
    d, c = max(window, key=lambda x: x[1])
    return date.fromisoformat(d), c


def generate_lots(isin: str, ticker: str, shares: int, current_price: float | None,
                  as_of: date) -> list[dict]:
    """Deterministic synthetic lots for one holding (see module docstring)."""
    if not shares or shares <= 0:
        return []
    rng = random.Random(_seed_for(isin))
    n_lots = min(rng.randint(2, 5), shares)

    # Months back per lot: lot 0 is guaranteed LTCG, lot 1 guaranteed STCG.
    months = []
    for i in range(n_lots):
        if i == 0:
            months.append(rng.randint(LTCG_HOLDING_MONTHS + 1, _MAX_MONTHS_BACK))
        elif i == 1:
            months.append(rng.randint(1, LTCG_HOLDING_MONTHS - 1))
        else:
            months.append(rng.randint(1, _MAX_MONTHS_BACK))

    loss_candidate = rng.random() < _LOSS_CANDIDATE_FRACTION

    # Split shares across lots with random weights (every lot >= 1 share).
    weights = [rng.uniform(0.5, 1.5) for _ in range(n_lots)]
    total_w = sum(weights)
    quantities = [max(int(shares * w / total_w), 1) for w in weights]
    quantities[0] += shares - sum(quantities)
    if quantities[0] < 1:  # rounding pushed lot 0 negative on tiny positions
        quantities = [shares] + [0] * (n_lots - 1)

    lots = []
    for i in range(n_lots):
        if quantities[i] <= 0:
            continue
        target = _shift_months(as_of, months[i])
        obs = None
        if loss_candidate and i == n_lots - 1:
            obs = _max_close_month(isin, as_of)
        if obs is None:
            obs = _close_near(isin, target)
        if obs is not None:
            acq_date, cost = obs
            if acq_date >= as_of:
                acq_date = target
        else:
            # No price history at all: drift off the current price.
            acq_date = target
            base = current_price or 100.0
            cost = round(base * rng.uniform(0.75, 1.25), 2)
        lots.append({
            "lot_id": f"{isin}-L{i + 1}",
            "acquisition_date": acq_date.isoformat(),
            "quantity": quantities[i],
            "cost_price": round(float(cost), 2),
            "source": "synthetic_curated",
        })
    return lots


def _scale_lots(lots: list[dict], shares: int) -> list[dict]:
    """Rescale persisted lot quantities so they sum to the holding's shares."""
    total = sum(l["quantity"] for l in lots)
    if total == shares or total <= 0 or shares <= 0:
        return lots
    scaled = []
    for l in lots:
        q = max(int(round(l["quantity"] * shares / total)), 0)
        scaled.append({**l, "quantity": q})
    drift = shares - sum(l["quantity"] for l in scaled)
    if scaled:
        scaled[0]["quantity"] += drift
    return [l for l in scaled if l["quantity"] > 0]


def _load_persisted() -> dict:
    global _persisted_cache
    if _persisted_cache is not None:
        return _persisted_cache
    persisted: dict[tuple, list] = {}
    if TAX_LOTS_CSV.exists():
        with open(TAX_LOTS_CSV, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    lot = {
                        "lot_id": row["lot_id"],
                        "acquisition_date": row["acquisition_date"],
                        "quantity": int(float(row["quantity"])),
                        "cost_price": float(row["cost_price"]),
                        "source": row.get("source", "synthetic_curated"),
                    }
                except (KeyError, ValueError, TypeError):
                    continue
                persisted.setdefault((row.get("fund_id"), row.get("isin")), []).append(lot)
    _persisted_cache = persisted
    return persisted


def _refresh_derived_fields(holding: dict, as_of: date) -> None:
    """Recompute avg_cost/stcg-ltcg split/effective rate from whatever is
    currently in holding["tax_lots"]. Shared by `attach_tax_data` and
    `apply_consumed_lots` (the latter mutates the lot list after the fact, so
    the derived fields need to be redone the same way)."""
    lots = holding.get("tax_lots") or []
    price = holding.get("price")
    total_cost = sum(l["cost_price"] * l["quantity"] for l in lots)
    total_qty = sum(l["quantity"] for l in lots)
    avg_cost = round(total_cost / total_qty, 2) if total_qty else None
    stcg_shares = sum(l["quantity"] for l in lots
                      if classify_term(date.fromisoformat(l["acquisition_date"]), as_of) == "STCG")

    holding["avg_cost"] = avg_cost
    holding["unrealized_gain_pct"] = (
        round((price - avg_cost) / avg_cost * 100, 2)
        if price and avg_cost else None)
    holding["stcg_shares"] = stcg_shares
    holding["ltcg_shares"] = total_qty - stcg_shares
    holding["effective_tax_rate_pct"] = round(
        effective_tax_rate(lots, price, as_of) * 100, 3) if price else 0.0


def attach_tax_data(fund_id: str, holding: dict, as_of: date) -> None:
    """Attach tax lots + derived tax fields to a holding (mutates in place)."""
    isin = holding.get("isin") or holding.get("ticker")
    shares = holding.get("shares") or 0
    price = holding.get("price")

    lots = _load_persisted().get((fund_id, isin))
    if lots:
        lots = _scale_lots([dict(l) for l in lots], shares)
        tax_source = "persisted_synthetic"
    else:
        lots = generate_lots(isin, holding.get("ticker", isin), shares, price, as_of)
        tax_source = "generated_synthetic"

    holding["tax_lots"] = lots
    holding["txn_cost_rate_pct"] = round(TXN_COST_SELL * 100, 4)
    holding["tax_source"] = tax_source
    _refresh_derived_fields(holding, as_of)


def apply_consumed_lots(holding: dict, consumed_by_lot_id: dict[str, int], as_of: date) -> None:
    """Reduce tax_lots by shares a prior approved+sent plan already sold from
    them, and refresh the derived fields to match. No-op if nothing of this
    holding's lots has been consumed yet. Caller must own `holding` (not a
    shared cached dict) since this mutates it."""
    if not consumed_by_lot_id:
        return
    lots = holding.get("tax_lots") or []
    if not any(l["lot_id"] in consumed_by_lot_id for l in lots):
        return
    new_lots = []
    for lot in lots:
        remaining = lot["quantity"] - consumed_by_lot_id.get(lot["lot_id"], 0)
        if remaining > 0:
            new_lots.append({**lot, "quantity": remaining})
    holding["tax_lots"] = new_lots
    _refresh_derived_fields(holding, as_of)


def sale_tax_breakdown(holding: dict, sell_price: float, sell_shares: int,
                       as_of: date) -> dict | None:
    """Per-order tax breakdown for selling `sell_shares` of this holding."""
    lots = holding.get("tax_lots")
    if not lots or not sell_price or sell_shares <= 0:
        return None
    return attribute_sale(lots, sell_price, sell_shares, as_of)


# --------------------------------------------------------------------------- #
# Generator script: python -m app.tax_lots
# --------------------------------------------------------------------------- #
def write_tax_lots_csv() -> Path:
    from . import data_v2  # lazy: data_v2 imports this module at startup

    as_of = data_v2.TODAY
    TAX_DIR.mkdir(parents=True, exist_ok=True)
    fields = ["fund_id", "ticker", "isin", "lot_id", "acquisition_date", "quantity",
              "cost_price", "cost_value", "holding_months", "term", "ltcg_date", "source"]
    rows = 0
    with open(TAX_LOTS_CSV, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for fund_id, ds in data_v2.FUNDS_V2.items():
            for h in ds["holdings"]:
                isin = h.get("isin") or h["ticker"]
                for lot in generate_lots(isin, h["ticker"], h.get("shares") or 0,
                                         h.get("price"), as_of):
                    acq = date.fromisoformat(lot["acquisition_date"])
                    writer.writerow({
                        "fund_id": fund_id,
                        "ticker": h["ticker"],
                        "isin": isin,
                        "lot_id": lot["lot_id"],
                        "acquisition_date": lot["acquisition_date"],
                        "quantity": lot["quantity"],
                        "cost_price": lot["cost_price"],
                        "cost_value": round(lot["cost_price"] * lot["quantity"], 2),
                        "holding_months": tax_rules.months_between(acq, as_of),
                        "term": classify_term(acq, as_of),
                        "ltcg_date": ltcg_date(acq).isoformat(),
                        "source": lot["source"],
                    })
                    rows += 1
    print(f"Wrote {rows} lots to {TAX_LOTS_CSV}")
    return TAX_LOTS_CSV


if __name__ == "__main__":
    write_tax_lots_csv()
