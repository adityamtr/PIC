"""
One-shot SQLite database initializer for the PIC Trade-Planning Platform.

Run this ONCE to create every table/index the platform needs and (by default)
seed the reference data that already exists in the repo:

  * funds & fund_holdings        <- backend/app/data_v2 (parsed disclosures, built fresh)
  * tax_lots                     <- backend/app/tax_lots (synthetic per-holding lots)
  * stocks & stock_prices        <- data/processed/equity_stock_universe.csv
                                    + data/processed/final/stock_macro_monthly_target.csv
  * macro_indicators             <- macro columns of the same monthly target file
  * predictions                  <- backend/predictions/**/predictions.json (TFT forecasts)
  * compliance/policy/tax rules  <- backend/app/{data_v2,policy,tax_rules} constants
  * plans (+ child tables)        <- empty; populated at runtime by the API

Once seeded, the application reads everything from this database and no longer
opens the raw XLSX/CSV feeds. Re-run this script (ideally with --reset) whenever
the source files or in-code rules change.

Usage (from the `backend/` directory or anywhere):

    python scripts/init_db.py                 # create schema + seed, at backend/database/pic.db
    python scripts/init_db.py --db-path X.db  # choose a different location
    python scripts/init_db.py --schema-only   # create tables only, no seeding
    python scripts/init_db.py --reset         # DROP existing tables first, then recreate

The script is idempotent: re-running it will not duplicate rows (seeds use
INSERT OR REPLACE / OR IGNORE against natural keys), and tables are created with
IF NOT EXISTS. Use --reset for a clean rebuild.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sqlite3
import sys
from datetime import date
from pathlib import Path

# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #
SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent                 # <repo>/backend
REPO_ROOT = BACKEND_DIR.parent                  # <repo>

# Honour the same PIC_DB_PATH override the application uses, so the seeder and
# the app always target the same file by default.
DEFAULT_DB_PATH = Path(os.environ["PIC_DB_PATH"]) if os.environ.get("PIC_DB_PATH") \
    else BACKEND_DIR / "database" / "pic.db"

UNIVERSE_CSV = REPO_ROOT / "data" / "processed" / "equity_stock_universe.csv"
TARGET_CSV = REPO_ROOT / "data" / "processed" / "final" / "stock_macro_monthly_target.csv"
PREDICTIONS_DIR = BACKEND_DIR / "predictions"

# Make `from app import ...` work when run as a plain script.
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


# --------------------------------------------------------------------------- #
# Schema (DDL)
# --------------------------------------------------------------------------- #
# Ordered list so --reset can drop children before parents.
TABLES = [
    "sent_emails", "email_drafts", "plan_decisions", "plan_risk_flags", "plan_compliance_checks",
    "plan_funding_sources", "plan_orders", "plans",
    "tax_rules", "esg_exclusions", "policy_thresholds",
    "compliance_rules", "fund_compliance_limits",
    "predictions", "tax_lots", "fund_holdings", "funds",
    "stock_prices", "macro_indicators", "stocks",
]

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

-- ------------------------------------------------------------------ --
-- Reference: securities (the investable universe / security master)
-- ------------------------------------------------------------------ --
CREATE TABLE IF NOT EXISTS stocks (
    isin                  TEXT PRIMARY KEY,
    symbol                TEXT,
    name                  TEXT,
    industry              TEXT,
    fund_count            INTEGER,
    total_percentage_nav  REAL
);
CREATE INDEX IF NOT EXISTS idx_stocks_symbol ON stocks(symbol);

-- Per-date macro backdrop shared by all securities.
CREATE TABLE IF NOT EXISTS macro_indicators (
    date                   TEXT PRIMARY KEY,
    oil_price_usd_bbl      REAL,
    oil_return_1m_pct      REAL,
    oil_return_12m_pct     REAL,
    gold_price_inr_10g     REAL,
    gold_return_1m_pct     REAL,
    gold_return_12m_pct    REAL,
    cpi_index              REAL,
    cpi_inflation_yoy_pct  REAL,
    inflation_change_1m    REAL,
    house_price_index      REAL,
    hpi_growth_12m_pct     REAL
);

-- Monthly OHLCV + engineered return history per security.
CREATE TABLE IF NOT EXISTS stock_prices (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    isin              TEXT NOT NULL,
    symbol            TEXT,
    date              TEXT NOT NULL,
    monthly_open      REAL,
    monthly_high      REAL,
    monthly_low       REAL,
    monthly_close     REAL,
    monthly_adj_close REAL,
    monthly_volume    REAL,
    trading_days      INTEGER,
    stock_return_1m   REAL,
    target_return_1m  REAL,
    UNIQUE(isin, date),
    FOREIGN KEY (isin) REFERENCES stocks(isin)
);
CREATE INDEX IF NOT EXISTS idx_stock_prices_isin_date ON stock_prices(isin, date);

-- ------------------------------------------------------------------ --
-- TFT predictions: one row per (security, prediction_date, version).
-- Query the newest run via the latest_predictions view below.
-- ------------------------------------------------------------------ --
CREATE TABLE IF NOT EXISTS predictions (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    isin             TEXT,
    symbol           TEXT,
    name             TEXT,
    prediction_date  TEXT NOT NULL,      -- as-of date of the forecast
    predicted_return REAL NOT NULL,      -- fractional 1-month forecast (0.05 = +5%)
    model_version    TEXT NOT NULL,
    created_at       TEXT DEFAULT (datetime('now')),
    UNIQUE(isin, prediction_date, model_version)
);
CREATE INDEX IF NOT EXISTS idx_predictions_date ON predictions(prediction_date);
CREATE INDEX IF NOT EXISTS idx_predictions_symbol ON predictions(symbol);

-- Only the most recent prediction run (per model version).
CREATE VIEW IF NOT EXISTS latest_predictions AS
SELECT p.*
FROM predictions p
JOIN (
    SELECT model_version, MAX(prediction_date) AS max_date
    FROM predictions
    GROUP BY model_version
) m ON p.model_version = m.model_version AND p.prediction_date = m.max_date;

-- ------------------------------------------------------------------ --
-- Funds and their holdings
-- ------------------------------------------------------------------ --
CREATE TABLE IF NOT EXISTS funds (
    fund_id        TEXT PRIMARY KEY,
    name           TEXT,
    amc            TEXT,
    category       TEXT,
    plan           TEXT,
    benchmark      TEXT,
    fund_manager   TEXT,
    inception      TEXT,
    nav            REAL,
    expense_ratio  REAL,
    risk_grade     TEXT,
    aum            REAL,
    currency       TEXT,
    as_of          TEXT,
    cash_total     REAL,
    cash_reserves  REAL,
    dataset_json   TEXT            -- full built dataset (holdings, trades, expense, events, ...)
);

CREATE TABLE IF NOT EXISTS fund_holdings (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    fund_id        TEXT NOT NULL,
    ticker         TEXT NOT NULL,
    name           TEXT,
    sector         TEXT,
    business_group TEXT,
    isin           TEXT,
    price          REAL,
    base_price     REAL,
    shares         INTEGER,
    market_value   REAL,
    target_weight  REAL,
    weight         REAL,
    drift_vs_target REAL,
    locked_shares  INTEGER,
    sellable_shares INTEGER,
    lock_in_expiry TEXT,
    lock_in_reason TEXT,
    raw_json       TEXT,            -- full holding dict (curated metadata, tax lots, ...)
    UNIQUE(fund_id, ticker),
    FOREIGN KEY (fund_id) REFERENCES funds(fund_id)
);
CREATE INDEX IF NOT EXISTS idx_holdings_fund ON fund_holdings(fund_id);
CREATE INDEX IF NOT EXISTS idx_holdings_isin ON fund_holdings(isin);

-- Synthetic per-holding tax lots (cost basis history) used by the tax-aware
-- planner. Also embedded in funds.dataset_json / fund_holdings.raw_json; this
-- table is the normalized, queryable copy.
CREATE TABLE IF NOT EXISTS tax_lots (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    fund_id          TEXT NOT NULL,
    ticker           TEXT,
    isin             TEXT,
    lot_id           TEXT,
    acquisition_date TEXT,
    quantity         INTEGER,
    cost_price       REAL,
    term             TEXT,          -- STCG / LTCG as of the seed date
    source           TEXT,
    UNIQUE(fund_id, lot_id),
    FOREIGN KEY (fund_id) REFERENCES funds(fund_id)
);
CREATE INDEX IF NOT EXISTS idx_tax_lots_fund ON tax_lots(fund_id);
CREATE INDEX IF NOT EXISTS idx_tax_lots_isin ON tax_lots(isin);

-- ------------------------------------------------------------------ --
-- Policy & compliance rules the application enforces
-- ------------------------------------------------------------------ --

-- Per-fund mandate caps (scalar limits). fund_id = 'DEFAULT' is the fallback
-- applied to any fund without its own tuned mandate.
CREATE TABLE IF NOT EXISTS fund_compliance_limits (
    fund_id            TEXT PRIMARY KEY,
    single_issuer_limit REAL,
    group_limit        REAL,
    sector_soft_limit  REAL,
    min_large_cap_pct  REAL,
    max_cash_pct       REAL
);

-- The named concentration rules attached to each fund's mandate.
CREATE TABLE IF NOT EXISTS compliance_rules (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    fund_id     TEXT NOT NULL,          -- 'DEFAULT' for the global rule set
    code        TEXT NOT NULL,
    name        TEXT,
    scope       TEXT,                   -- issuer / group / sector
    limit_value REAL,
    description TEXT,
    UNIQUE(fund_id, code)
);
CREATE INDEX IF NOT EXISTS idx_rules_fund ON compliance_rules(fund_id);

-- Pre-trade policy-engine thresholds (policy.POLICY_DEFAULTS), versioned.
CREATE TABLE IF NOT EXISTS policy_thresholds (
    policy_version TEXT NOT NULL,
    key            TEXT NOT NULL,
    value          REAL,
    PRIMARY KEY (policy_version, key)
);

-- Securities excluded from new purchases on ESG grounds.
CREATE TABLE IF NOT EXISTS esg_exclusions (
    ticker       TEXT PRIMARY KEY,
    activity     TEXT,
    exposure_pct REAL
);

-- Taxation rates & charges (one row per financial year).
CREATE TABLE IF NOT EXISTS tax_rules (
    financial_year       TEXT PRIMARY KEY,
    stcg_rate_pct        REAL,
    ltcg_rate_pct        REAL,
    ltcg_exemption_inr   REAL,
    ltcg_holding_months  INTEGER,
    stt_sell_pct         REAL,
    stamp_duty_buy_pct   REAL,
    brokerage_pct        REAL,
    exchange_charges_pct REAL
);

-- ------------------------------------------------------------------ --
-- Generated trade plans (hybrid: indexed columns + full JSON) & children
-- ------------------------------------------------------------------ --
CREATE TABLE IF NOT EXISTS plans (
    plan_id            TEXT PRIMARY KEY,
    fund_id            TEXT,
    fund_name          TEXT,
    created_at         TEXT,
    status             TEXT,
    action             TEXT,
    target             TEXT,
    amount_cr          REAL,
    horizon_days       INTEGER,
    trade_date         TEXT,
    settlement_date    TEXT,
    allocation_method  TEXT,
    compliance_status  TEXT,
    policy_status      TEXT,
    execution_allowed  INTEGER,
    recommendation     TEXT,
    order_count        INTEGER,
    total_buy_value    REAL,
    total_sell_value   REAL,
    net_cash_impact    REAL,
    investable_amount  REAL,
    est_total_tax      REAL,
    plan_json          TEXT NOT NULL,   -- full plan document (lossless)
    FOREIGN KEY (fund_id) REFERENCES funds(fund_id)
);
CREATE INDEX IF NOT EXISTS idx_plans_fund ON plans(fund_id);
CREATE INDEX IF NOT EXISTS idx_plans_status ON plans(status);
CREATE INDEX IF NOT EXISTS idx_plans_created ON plans(created_at);

CREATE TABLE IF NOT EXISTS sent_emails (
    email_id   TEXT PRIMARY KEY,
    plan_id    TEXT NOT NULL,
    subject    TEXT NOT NULL,
    body       TEXT NOT NULL,
    model      TEXT NOT NULL,
    sent_at    TEXT NOT NULL,
    FOREIGN KEY (plan_id) REFERENCES plans(plan_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_sent_emails_plan_sent
    ON sent_emails(plan_id, sent_at DESC);

CREATE TABLE IF NOT EXISTS plan_orders (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id         TEXT NOT NULL,
    ticker          TEXT,
    name            TEXT,
    sector          TEXT,
    side            TEXT,
    shares          INTEGER,
    price           REAL,
    est_value       REAL,
    expected_return REAL,
    reason          TEXT,
    trade_date      TEXT,
    settlement_date TEXT,
    tax_json        TEXT,
    FOREIGN KEY (plan_id) REFERENCES plans(plan_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_orders_plan ON plan_orders(plan_id);

CREATE TABLE IF NOT EXISTS plan_funding_sources (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id   TEXT NOT NULL,
    ticker    TEXT,
    name      TEXT,
    sector    TEXT,
    side      TEXT,
    shares    INTEGER,
    price     REAL,
    est_value REAL,
    reason    TEXT,
    FOREIGN KEY (plan_id) REFERENCES plans(plan_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_funding_plan ON plan_funding_sources(plan_id);

CREATE TABLE IF NOT EXISTS plan_compliance_checks (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id       TEXT NOT NULL,
    code          TEXT,
    rule          TEXT,
    entity        TEXT,
    current_value REAL,
    projected     REAL,
    limit_value   REAL,
    status        TEXT,
    message       TEXT,
    FOREIGN KEY (plan_id) REFERENCES plans(plan_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_compliance_plan ON plan_compliance_checks(plan_id);

CREATE TABLE IF NOT EXISTS plan_risk_flags (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id  TEXT NOT NULL,
    type     TEXT,
    severity TEXT,
    ticker   TEXT,
    message  TEXT,
    FOREIGN KEY (plan_id) REFERENCES plans(plan_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_risk_plan ON plan_risk_flags(plan_id);

CREATE TABLE IF NOT EXISTS plan_decisions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id    TEXT NOT NULL,
    decision   TEXT,
    reviewer   TEXT,
    comment    TEXT,
    decided_at TEXT,
    FOREIGN KEY (plan_id) REFERENCES plans(plan_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_decision_plan ON plan_decisions(plan_id);
"""


# --------------------------------------------------------------------------- #
# Parsing helpers
# --------------------------------------------------------------------------- #
def _f(value):
    """Parse a CSV cell into float or None."""
    if value is None:
        return None
    s = str(value).strip()
    if s == "" or s.lower() in ("nan", "none", "null"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _i(value):
    f = _f(value)
    return int(f) if f is not None else None


# --------------------------------------------------------------------------- #
# Schema management
# --------------------------------------------------------------------------- #
def create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)
    conn.commit()


def drop_all(conn: sqlite3.Connection) -> None:
    conn.execute("DROP VIEW IF EXISTS latest_predictions")
    for table in TABLES:
        conn.execute(f"DROP TABLE IF EXISTS {table}")
    conn.commit()


# --------------------------------------------------------------------------- #
# Seeders
# --------------------------------------------------------------------------- #
def seed_stocks(conn: sqlite3.Connection) -> int:
    """Security master from the equity universe, enriched with symbols from prices."""
    if not UNIVERSE_CSV.exists():
        print(f"  ! skipping stocks: {UNIVERSE_CSV} not found")
        return 0

    # isin -> symbol from the monthly file (universe csv has no ticker symbol).
    symbol_by_isin: dict[str, str] = {}
    if TARGET_CSV.exists():
        with TARGET_CSV.open(encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                isin, sym = row.get("isin"), row.get("symbol")
                if isin and sym and isin not in symbol_by_isin:
                    symbol_by_isin[isin] = sym

    rows = []
    with UNIVERSE_CSV.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            isin = (row.get("security_isin") or "").strip()
            if not isin:
                continue
            rows.append((
                isin,
                symbol_by_isin.get(isin),
                (row.get("security_name") or "").strip() or None,
                (row.get("industry") or "").strip() or None,
                _i(row.get("fund_count")),
                _f(row.get("total_percentage_nav")),
            ))

    # Include any ISIN seen only in the price file so foreign keys resolve.
    known = {r[0] for r in rows}
    for isin, sym in symbol_by_isin.items():
        if isin not in known:
            rows.append((isin, sym, sym, None, None, None))

    conn.executemany(
        "INSERT OR REPLACE INTO stocks "
        "(isin, symbol, name, industry, fund_count, total_percentage_nav) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    return len(rows)


def seed_prices_and_macro(conn: sqlite3.Connection) -> tuple[int, int]:
    """Monthly OHLCV/returns -> stock_prices; shared macro columns -> macro_indicators."""
    if not TARGET_CSV.exists():
        print(f"  ! skipping prices/macro: {TARGET_CSV} not found")
        return (0, 0)

    price_rows, macro_by_date = [], {}
    with TARGET_CSV.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            isin = (row.get("isin") or "").strip()
            d = (row.get("date") or "").strip()
            if not isin or not d:
                continue
            price_rows.append((
                isin, (row.get("symbol") or "").strip() or None, d,
                _f(row.get("monthly_open")), _f(row.get("monthly_high")),
                _f(row.get("monthly_low")), _f(row.get("monthly_close")),
                _f(row.get("monthly_adj_close")), _f(row.get("monthly_volume")),
                _i(row.get("trading_days")), _f(row.get("stock_return_1m")),
                _f(row.get("target_return_1m")),
            ))
            if d not in macro_by_date:
                macro_by_date[d] = (
                    d,
                    _f(row.get("oil_price_usd_bbl")), _f(row.get("oil_return_1m_pct")),
                    _f(row.get("oil_return_12m_pct")), _f(row.get("gold_price_inr_10g")),
                    _f(row.get("gold_return_1m_pct")), _f(row.get("gold_return_12m_pct")),
                    _f(row.get("cpi_index")), _f(row.get("cpi_inflation_yoy_pct")),
                    _f(row.get("inflation_change_1m")), _f(row.get("house_price_index")),
                    _f(row.get("hpi_growth_12m_pct")),
                )

    conn.executemany(
        "INSERT OR IGNORE INTO macro_indicators VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        list(macro_by_date.values()),
    )
    conn.executemany(
        "INSERT OR IGNORE INTO stock_prices "
        "(isin, symbol, date, monthly_open, monthly_high, monthly_low, monthly_close, "
        " monthly_adj_close, monthly_volume, trading_days, stock_return_1m, target_return_1m) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        price_rows,
    )
    conn.commit()
    return (len(price_rows), len(macro_by_date))


def build_source_datasets() -> dict:
    """Build fund datasets straight from the raw disclosures (XLSX/CSV), bypassing
    any data already in the database, so re-seeding always reflects the files."""
    try:
        from app import data_v2  # noqa: WPS433 (heavy: parses XLSX + price feed)
        return data_v2.build_datasets_from_source()
    except Exception as exc:  # pragma: no cover - environment dependent
        print(f"  ! could not build fund datasets from source ({exc})")
        return {}


def seed_funds(conn: sqlite3.Connection, datasets: dict) -> tuple[int, int]:
    """Funds and holdings from freshly-built source datasets."""
    if not datasets:
        print("  ! skipping funds: no datasets available")
        return (0, 0)

    fund_rows, holding_rows = [], []
    for ds in datasets.values():
        f = ds["fund"]
        cash = ds.get("cash", {})
        # Full built dataset for lossless reconstruction (holdings_by_ticker is
        # derived at read time, so drop it before serializing).
        ds_serializable = {k: v for k, v in ds.items() if k != "holdings_by_ticker"}
        fund_rows.append((
            ds["id"], f.get("name"), f.get("amc"), f.get("category"), f.get("plan"),
            f.get("benchmark"), f.get("fund_manager"), f.get("inception"), _f(f.get("nav")),
            _f(f.get("expense_ratio")), f.get("risk_grade"), _f(f.get("aum")),
            f.get("currency"), f.get("as_of"),
            _f(cash.get("total_cash")), _f(cash.get("reserves")),
            json.dumps(ds_serializable, default=str),
        ))
        for h in ds["holdings"]:
            holding_rows.append((
                ds["id"], h.get("ticker"), h.get("name"), h.get("sector"), h.get("group"),
                h.get("isin"), _f(h.get("price")), _f(h.get("base_price")), _i(h.get("shares")),
                _f(h.get("market_value")), _f(h.get("target_weight")), _f(h.get("weight")),
                _f(h.get("drift_vs_target")), _i(h.get("locked_shares")),
                _i(h.get("sellable_shares")), h.get("lock_in_expiry"), h.get("lock_in_reason"),
                json.dumps(h, default=str),
            ))

    conn.executemany(
        "INSERT OR REPLACE INTO funds "
        "(fund_id, name, amc, category, plan, benchmark, fund_manager, inception, nav, "
        " expense_ratio, risk_grade, aum, currency, as_of, cash_total, cash_reserves, dataset_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        fund_rows,
    )
    conn.executemany(
        "INSERT OR REPLACE INTO fund_holdings "
        "(fund_id, ticker, name, sector, business_group, isin, price, base_price, shares, "
        " market_value, target_weight, weight, drift_vs_target, locked_shares, sellable_shares, "
        " lock_in_expiry, lock_in_reason, raw_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        holding_rows,
    )
    conn.commit()
    return (len(fund_rows), len(holding_rows))


def seed_tax_lots(conn: sqlite3.Connection, datasets: dict) -> int:
    """Normalized copy of the synthetic per-holding tax lots embedded in each
    dataset's holdings."""
    if not datasets:
        return 0
    try:
        from datetime import date as _date

        from app import tax_rules  # noqa: WPS433
        as_of = _date.today()
    except Exception:  # pragma: no cover
        tax_rules = None
        as_of = None

    rows = []
    for ds in datasets.values():
        fund_id = ds["id"]
        for h in ds["holdings"]:
            for lot in h.get("tax_lots", []) or []:
                term = None
                if tax_rules is not None and lot.get("acquisition_date"):
                    try:
                        term = tax_rules.classify_term(
                            _date.fromisoformat(lot["acquisition_date"]), as_of)
                    except Exception:
                        term = None
                rows.append((
                    fund_id, h.get("ticker"), h.get("isin"), lot.get("lot_id"),
                    lot.get("acquisition_date"), _i(lot.get("quantity")),
                    _f(lot.get("cost_price")), term, lot.get("source"),
                ))

    conn.executemany(
        "INSERT OR REPLACE INTO tax_lots "
        "(fund_id, ticker, isin, lot_id, acquisition_date, quantity, cost_price, term, source) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    # Report the persisted count (UNIQUE(fund_id, lot_id) collapses any lots that
    # share an id, e.g. duplicate holdings that map to the same ISIN).
    return conn.execute("SELECT COUNT(*) FROM tax_lots").fetchone()[0]


def seed_compliance(conn: sqlite3.Connection) -> dict[str, int]:
    """Persist the mandate limits, policy thresholds, ESG exclusions and tax rules
    that the planner/policy engine enforce at runtime."""
    try:
        from app import data_v2, policy, tax_rules  # noqa: WPS433
    except Exception as exc:  # pragma: no cover - environment dependent
        print(f"  ! skipping compliance rules: could not import app modules ({exc})")
        return {}

    # Fund mandate caps + named rules ('DEFAULT' + one entry per tuned fund).
    limit_sets = {"DEFAULT": data_v2.COMPLIANCE_LIMITS, **data_v2.FUND_COMPLIANCE_LIMITS}
    limit_rows, rule_rows = [], []
    for fund_id, lim in limit_sets.items():
        limit_rows.append((
            fund_id, _f(lim.get("single_issuer_limit")), _f(lim.get("group_limit")),
            _f(lim.get("sector_soft_limit")), _f(lim.get("min_large_cap_pct")),
            _f(lim.get("max_cash_pct")),
        ))
        for rule in lim.get("rules", []):
            rule_rows.append((
                fund_id, rule.get("code"), rule.get("name"), rule.get("scope"),
                _f(rule.get("limit")), rule.get("description"),
            ))

    conn.executemany(
        "INSERT OR REPLACE INTO fund_compliance_limits "
        "(fund_id, single_issuer_limit, group_limit, sector_soft_limit, "
        " min_large_cap_pct, max_cash_pct) VALUES (?, ?, ?, ?, ?, ?)",
        limit_rows,
    )
    conn.executemany(
        "INSERT OR REPLACE INTO compliance_rules "
        "(fund_id, code, name, scope, limit_value, description) VALUES (?, ?, ?, ?, ?, ?)",
        rule_rows,
    )

    # Policy-engine thresholds (versioned).
    version = policy.POLICY_VERSION
    threshold_rows = [(version, k, _f(v)) for k, v in policy.POLICY_DEFAULTS.items()]
    conn.executemany(
        "INSERT OR REPLACE INTO policy_thresholds (policy_version, key, value) VALUES (?, ?, ?)",
        threshold_rows,
    )

    # ESG buy exclusions.
    esg_rows = [
        (ticker, info.get("activity"), _f(info.get("exposure_pct")))
        for ticker, info in policy.ESG_EXCLUSIONS.items()
    ]
    conn.executemany(
        "INSERT OR REPLACE INTO esg_exclusions (ticker, activity, exposure_pct) VALUES (?, ?, ?)",
        esg_rows,
    )

    # Taxation rates & charges.
    r = tax_rules.RATES
    conn.execute(
        "INSERT OR REPLACE INTO tax_rules "
        "(financial_year, stcg_rate_pct, ltcg_rate_pct, ltcg_exemption_inr, "
        " ltcg_holding_months, stt_sell_pct, stamp_duty_buy_pct, brokerage_pct, "
        " exchange_charges_pct) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            r.get("financial_year"), _f(r.get("stcg_rate_pct")), _f(r.get("ltcg_rate_pct")),
            _f(r.get("ltcg_exemption_inr")), _i(r.get("ltcg_holding_months")),
            _f(r.get("stt_sell_pct")), _f(r.get("stamp_duty_buy_pct")),
            _f(r.get("brokerage_pct")), _f(r.get("exchange_charges_pct")),
        ),
    )

    conn.commit()
    return {
        "fund_limits": len(limit_rows),
        "rules": len(rule_rows),
        "policy_thresholds": len(threshold_rows),
        "esg_exclusions": len(esg_rows),
        "tax_rules": 1,
    }


def _prediction_files() -> list[tuple[str, Path]]:
    """Return (model_version, path) for every predictions.json in the repo."""
    found: list[tuple[str, Path]] = []
    # Versioned files: backend/predictions/v*/predictions.json
    for path in sorted(PREDICTIONS_DIR.glob("v*/predictions.json")):
        found.append((path.parent.name, path))
    # Top-level file is treated as "v2" by app.forecast.
    top = PREDICTIONS_DIR / "predictions.json"
    if top.is_file() and not any(v == "v2" for v, _ in found):
        found.append(("v2", top))
    return found


def seed_predictions(conn: sqlite3.Connection) -> int:
    """Load TFT forecasts (symbol -> fractional return) into one row per security.

    The stored ``prediction_date`` is the latest data date in the monthly file
    (the as-of anchor of a 1-month-ahead forecast). ISIN and name are resolved
    from the ``stocks`` table.
    """
    files = _prediction_files()
    if not files:
        print("  ! skipping predictions: no predictions.json found")
        return 0

    # symbol -> (isin, name) from the security master we just seeded.
    by_symbol: dict[str, tuple[str, str | None]] = {}
    for isin, symbol, name in conn.execute(
        "SELECT isin, symbol, name FROM stocks WHERE symbol IS NOT NULL"
    ):
        by_symbol.setdefault(symbol, (isin, name))

    # As-of date = newest date present in the price history (fallback: today).
    row = conn.execute("SELECT MAX(date) FROM stock_prices").fetchone()
    prediction_date = (row and row[0]) or date.today().isoformat()

    total = 0
    for version, path in files:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"  ! skipping {path}: {exc}")
            continue

        rows = []
        for symbol, value in payload.items():
            if value is None:
                continue
            isin, name = by_symbol.get(symbol, (None, None))
            rows.append((isin, symbol, name, prediction_date, float(value), version))
        conn.executemany(
            "INSERT OR REPLACE INTO predictions "
            "(isin, symbol, name, prediction_date, predicted_return, model_version) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            rows,
        )
        total += len(rows)
        print(f"    - {version}: {len(rows)} predictions (as of {prediction_date})")

    conn.commit()
    return total


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def main() -> None:
    parser = argparse.ArgumentParser(description="Initialize the PIC SQLite database.")
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH,
                        help=f"SQLite file to create (default: {DEFAULT_DB_PATH}).")
    parser.add_argument("--schema-only", action="store_true",
                        help="Create tables/indexes only; do not seed reference data.")
    parser.add_argument("--reset", action="store_true",
                        help="Drop existing PIC tables before creating them.")
    args = parser.parse_args()

    args.db_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"Database: {args.db_path.resolve()}")

    conn = sqlite3.connect(args.db_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON")

        if args.reset:
            print("Dropping existing tables (--reset) ...")
            drop_all(conn)

        print("Creating schema ...")
        create_schema(conn)
        print(f"  created {len(TABLES)} tables + latest_predictions view")

        if args.schema_only:
            print("Schema-only mode: skipping seed.")
        else:
            print("Seeding reference data ...")
            n_stocks = seed_stocks(conn)
            print(f"  stocks:      {n_stocks}")
            n_prices, n_macro = seed_prices_and_macro(conn)
            print(f"  stock_prices:{n_prices}   macro_indicators:{n_macro}")
            datasets = build_source_datasets()   # build once from XLSX/CSV, reuse below
            n_funds, n_holdings = seed_funds(conn, datasets)
            print(f"  funds:       {n_funds}   fund_holdings:{n_holdings}")
            n_lots = seed_tax_lots(conn, datasets)
            print(f"  tax_lots:    {n_lots}")
            n_pred = seed_predictions(conn)
            print(f"  predictions: {n_pred}")
            rules = seed_compliance(conn)
            if rules:
                print(f"  fund_compliance_limits:{rules['fund_limits']}   "
                      f"compliance_rules:{rules['rules']}   "
                      f"policy_thresholds:{rules['policy_thresholds']}   "
                      f"esg_exclusions:{rules['esg_exclusions']}   "
                      f"tax_rules:{rules['tax_rules']}")

        print("Done.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
