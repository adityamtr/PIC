"""
SQLite gateway for the PIC platform.

A thin, dependency-free access layer over the database created by
``backend/scripts/init_db.py``. Every read helper degrades gracefully: if the
database file is missing or a table is empty it returns ``None`` (or an empty
collection) so callers transparently fall back to their in-code defaults. This
keeps the app runnable even before ``init_db.py`` has been run.

Location resolution order:
  1. ``PIC_DB_PATH`` environment variable, if set.
  2. ``<repo>/backend/database/pic.db`` (the init script's default).
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from pathlib import Path
from typing import Any

_BACKEND_DIR = Path(__file__).resolve().parent.parent
_DEFAULT_DB_PATH = _BACKEND_DIR / "database" / "pic.db"

_LOCK = threading.Lock()


def db_path() -> Path:
    """Resolve the active database path (env override, else the default)."""
    override = os.environ.get("PIC_DB_PATH")
    return Path(override) if override else _DEFAULT_DB_PATH


def available() -> bool:
    """True when a database file exists at the resolved path."""
    return db_path().is_file()


def connect() -> sqlite3.Connection:
    """Open a connection with row access by column name and FKs enabled."""
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _table_has_rows(conn: sqlite3.Connection, table: str) -> bool:
    try:
        return conn.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone() is not None
    except sqlite3.Error:
        return False


# --------------------------------------------------------------------------- #
# Predictions (read)
# --------------------------------------------------------------------------- #
def get_latest_predictions(model_version: str) -> dict[str, float] | None:
    """Return ``{symbol: predicted_return}`` for the newest prediction date of a
    given model version, or ``None`` if unavailable."""
    if not available():
        return None
    try:
        with connect() as conn:
            row = conn.execute(
                "SELECT MAX(prediction_date) FROM predictions WHERE model_version = ?",
                (model_version,),
            ).fetchone()
            if not row or row[0] is None:
                return None
            latest = row[0]
            rows = conn.execute(
                "SELECT symbol, predicted_return FROM predictions "
                "WHERE model_version = ? AND prediction_date = ?",
                (model_version, latest),
            ).fetchall()
    except sqlite3.Error:
        return None
    predictions = {r["symbol"]: r["predicted_return"] for r in rows if r["symbol"]}
    return predictions or None


# --------------------------------------------------------------------------- #
# Funds & holdings (read)
# --------------------------------------------------------------------------- #
def list_fund_datasets() -> dict[str, dict] | None:
    """Return ``{fund_id: ds}`` for every fund whose full dataset JSON is stored,
    or ``None`` if the funds table is unavailable/empty."""
    if not available():
        return None
    try:
        with connect() as conn:
            if not _table_has_rows(conn, "funds"):
                return None
            rows = conn.execute(
                "SELECT fund_id, dataset_json FROM funds WHERE dataset_json IS NOT NULL"
            ).fetchall()
    except sqlite3.Error:
        return None
    datasets: dict[str, dict] = {}
    for row in rows:
        try:
            ds = json.loads(row["dataset_json"])
        except (TypeError, json.JSONDecodeError):
            continue
        # holdings_by_ticker is derived (and not serialized) — rebuild it.
        ds["holdings_by_ticker"] = {h["ticker"]: h for h in ds.get("holdings", [])}
        datasets[row["fund_id"]] = ds
    return datasets or None


# --------------------------------------------------------------------------- #
# Compliance & policy rules (read)
# --------------------------------------------------------------------------- #
def get_compliance_limits(fund_id: str) -> dict[str, Any] | None:
    """Reconstruct a fund's mandate-limit dict (scalars + ``rules`` list) from the
    ``fund_compliance_limits`` / ``compliance_rules`` tables, or ``None``."""
    if not available():
        return None
    try:
        with connect() as conn:
            limit_row = conn.execute(
                "SELECT single_issuer_limit, group_limit, sector_soft_limit, "
                "min_large_cap_pct, max_cash_pct FROM fund_compliance_limits "
                "WHERE fund_id = ?",
                (fund_id,),
            ).fetchone()
            if limit_row is None:
                return None
            rule_rows = conn.execute(
                "SELECT code, name, scope, limit_value, description FROM compliance_rules "
                "WHERE fund_id = ?",
                (fund_id,),
            ).fetchall()
    except sqlite3.Error:
        return None
    return {
        "single_issuer_limit": limit_row["single_issuer_limit"],
        "group_limit": limit_row["group_limit"],
        "sector_soft_limit": limit_row["sector_soft_limit"],
        "min_large_cap_pct": limit_row["min_large_cap_pct"],
        "max_cash_pct": limit_row["max_cash_pct"],
        "rules": [
            {"code": r["code"], "name": r["name"], "scope": r["scope"],
             "limit": r["limit_value"], "description": r["description"]}
            for r in rule_rows
        ],
    }


def get_policy_thresholds(policy_version: str | None = None) -> dict[str, float] | None:
    """Return ``{key: value}`` for policy thresholds. When ``policy_version`` is
    omitted, the newest version present is used."""
    if not available():
        return None
    try:
        with connect() as conn:
            if policy_version is None:
                row = conn.execute("SELECT MAX(policy_version) FROM policy_thresholds").fetchone()
                if not row or row[0] is None:
                    return None
                policy_version = row[0]
            rows = conn.execute(
                "SELECT key, value FROM policy_thresholds WHERE policy_version = ?",
                (policy_version,),
            ).fetchall()
    except sqlite3.Error:
        return None
    return {r["key"]: r["value"] for r in rows} or None


def get_esg_exclusions() -> dict[str, dict] | None:
    """Return ``{ticker: {activity, exposure_pct}}`` or ``None``."""
    if not available():
        return None
    try:
        with connect() as conn:
            rows = conn.execute(
                "SELECT ticker, activity, exposure_pct FROM esg_exclusions"
            ).fetchall()
    except sqlite3.Error:
        return None
    return {
        r["ticker"]: {"activity": r["activity"], "exposure_pct": r["exposure_pct"]}
        for r in rows
    } or None


def get_tax_rates() -> dict[str, Any] | None:
    """Return the most recent financial year's tax rate row as a dict, or ``None``."""
    if not available():
        return None
    try:
        with connect() as conn:
            row = conn.execute(
                "SELECT * FROM tax_rules ORDER BY financial_year DESC LIMIT 1"
            ).fetchone()
    except sqlite3.Error:
        return None
    return dict(row) if row else None


# --------------------------------------------------------------------------- #
# Plans & decisions (read / write)
# --------------------------------------------------------------------------- #
def save_plan(plan: dict) -> bool:
    """Persist a generated plan into ``plans`` plus its child tables. Returns
    ``True`` on success, ``False`` if the database is unavailable."""
    if not available():
        return False
    summary = plan.get("summary", {})
    intent = plan.get("intent", {})
    fund = plan.get("fund", {})
    try:
        with _LOCK, connect() as conn:
            conn.execute("DELETE FROM plans WHERE plan_id = ?", (plan["plan_id"],))
            conn.execute(
                "INSERT INTO plans (plan_id, fund_id, fund_name, created_at, status, action, "
                "target, amount_cr, horizon_days, trade_date, settlement_date, allocation_method, "
                "compliance_status, policy_status, execution_allowed, recommendation, order_count, "
                "total_buy_value, total_sell_value, net_cash_impact, investable_amount, "
                "est_total_tax, plan_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    plan["plan_id"], fund.get("fund_id"), fund.get("name"),
                    plan.get("created_at"), plan.get("status"), intent.get("action"),
                    intent.get("target"), intent.get("amount_cr"), intent.get("horizon_days"),
                    intent.get("trade_date"), intent.get("settlement_date"),
                    plan.get("allocation_method"), summary.get("compliance_status"),
                    plan.get("policy_status"), 1 if plan.get("execution_allowed") else 0,
                    plan.get("recommendation"), summary.get("order_count"),
                    summary.get("total_buy_value"), summary.get("total_sell_value"),
                    summary.get("net_cash_impact"), summary.get("investable_amount"),
                    summary.get("est_total_tax"),
                    json.dumps(plan, default=str),
                ),
            )
            conn.executemany(
                "INSERT INTO plan_orders (plan_id, ticker, name, sector, side, shares, price, "
                "est_value, expected_return, reason, trade_date, settlement_date, tax_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (plan["plan_id"], o.get("ticker"), o.get("name"), o.get("sector"),
                     o.get("side"), o.get("shares"), o.get("price"), o.get("est_value"),
                     o.get("expected_return"), o.get("reason"), o.get("trade_date"),
                     o.get("settlement_date"),
                     json.dumps(o["tax"], default=str) if o.get("tax") else None)
                    for o in plan.get("orders", [])
                ],
            )
            conn.executemany(
                "INSERT INTO plan_funding_sources (plan_id, ticker, name, sector, side, shares, "
                "price, est_value, reason) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (plan["plan_id"], s.get("ticker"), s.get("name"), s.get("sector"),
                     s.get("side"), s.get("shares"), s.get("price"), s.get("est_value"),
                     s.get("reason"))
                    for s in plan.get("funding_sources", [])
                ],
            )
            conn.executemany(
                "INSERT INTO plan_compliance_checks (plan_id, code, rule, entity, current_value, "
                "projected, limit_value, status, message) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (plan["plan_id"], c.get("code"), c.get("rule"), c.get("entity"),
                     c.get("current"), c.get("projected"), c.get("limit"), c.get("status"),
                     c.get("message"))
                    for c in plan.get("compliance_checks", [])
                ],
            )
            conn.executemany(
                "INSERT INTO plan_risk_flags (plan_id, type, severity, ticker, message) "
                "VALUES (?, ?, ?, ?, ?)",
                [
                    (plan["plan_id"], f.get("type"), f.get("severity"), f.get("ticker"),
                     f.get("message"))
                    for f in plan.get("risk_flags", [])
                ],
            )
    except sqlite3.Error:
        return False
    return True


def get_plan(plan_id: str) -> dict | None:
    """Return the full stored plan document, or ``None`` if not found."""
    if not available():
        return None
    try:
        with connect() as conn:
            row = conn.execute(
                "SELECT plan_json FROM plans WHERE plan_id = ?", (plan_id,)
            ).fetchone()
    except sqlite3.Error:
        return None
    if not row:
        return None
    try:
        return json.loads(row["plan_json"])
    except (TypeError, json.JSONDecodeError):
        return None


def save_decision(plan_id: str, status: str, decision: dict) -> bool:
    """Record a PIC decision: append to ``plan_decisions`` and update the plan's
    status + embedded decision in ``plan_json``. Returns ``False`` if unavailable
    or the plan is unknown."""
    if not available():
        return False
    try:
        with _LOCK, connect() as conn:
            row = conn.execute(
                "SELECT plan_json FROM plans WHERE plan_id = ?", (plan_id,)
            ).fetchone()
            if not row:
                return False
            plan = json.loads(row["plan_json"])
            plan["status"] = status
            plan["decision"] = decision
            conn.execute(
                "UPDATE plans SET status = ?, plan_json = ? WHERE plan_id = ?",
                (status, json.dumps(plan, default=str), plan_id),
            )
            conn.execute(
                "INSERT INTO plan_decisions (plan_id, decision, reviewer, comment, decided_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (plan_id, decision.get("decision"), decision.get("reviewer"),
                 decision.get("comment"), decision.get("decided_at")),
            )
    except sqlite3.Error:
        return False
    return True
