"""
PIC Trade-Plan API (FastAPI), multi-fund.

Exposes synthetic portfolio data and the trade-plan generation engine. This is
the automated "middle layer": it converts a PM's intent into a review-ready
trading plan. A PIC associate approves it. Recommends — does not decide.

Most read endpoints accept an optional `?fund_id=` query parameter; when omitted
the default fund is used.
"""

from __future__ import annotations

import asyncio
import json
import random
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse

from . import assistant, data, data_v2, db, email_draft, forecast, planner
from .schemas import (
    AssistantChatRequest, AssistantChatResponse, AssistantInterpretRequest,
    DecisionRequest, DecisionResponse, EmailDraftResponse, IntentRequest,
    SendEmailRequest, SentEmailResponse,
)

app = FastAPI(
    title="PIC Trade-Plan API",
    description="Cash-flow planning, trade-plan generation, compliance checks and "
                "risk detection across multiple funds. Recommends — does not decide.",
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_credentials=False,
    allow_methods=["*"], allow_headers=["*"],
)

_PLANS: dict[str, dict] = {}
_BACKEND_DIR = Path(__file__).resolve().parent.parent


def _to_cr(value):
    return round(value / data_v2.CRORE, 2)


def _ds(fund_id):
    """Load fund dataset, augmented with approved-plan orders as pending trades
    so all endpoints see the full cross-plan commitment picture. Returns a
    shallow copy to avoid mutating the cached dataset."""
    ds = data_v2.get_ds(fund_id)
    # Create a new pending_trades list (don't mutate the cached one) by combining
    # static trades + approved-plan orders.
    augmented_ds = dict(ds)
    augmented_ds["pending_trades"] = (
        list(ds["pending_trades"]) +
        planner._augment_pending_trades_from_approved_plans(fund_id)
    )
    return augmented_ds


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "pic-trade-plan-api", "version": app.version}


@app.get("/api/model")
def get_model_info():
    """Return current active model version, available versions, and model metadata."""
    return forecast.get_active_model_info()


@app.post("/api/model/switch")
def switch_model_version(version: str = Query(..., description="Target model version (e.g. 'v1', 'v2', 'latest')")):
    """Switch active model version across the application in one go."""
    new_version = forecast.set_active_model_version(version)
    return {"status": "success", "switched_to": new_version, "model": forecast.get_active_model_info()}


@app.post("/api/admin/reset-db")
def reset_database():
    """Drop, recreate, and reseed the SQLite database from source data (same as
    running ``scripts/init_db.py --reset`` from a terminal). Destructive: wipes
    every generated plan/decision and any in-session edits to fund data."""
    script = _BACKEND_DIR / "scripts" / "init_db.py"
    try:
        result = subprocess.run(
            [sys.executable, str(script), "--reset", "--db-path", str(db.db_path())],
            cwd=str(_BACKEND_DIR), capture_output=True, text=True, timeout=180,
        )
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(status_code=504, detail="Database reset timed out") from exc
    if result.returncode != 0:
        raise HTTPException(status_code=500, detail=result.stderr[-2000:] or "Database reset failed")
    _PLANS.clear()   # drop any not-yet-decided plans generated before the reset
    return {"status": "reset", "db_path": str(db.db_path())}


@app.get("/api/funds")
def get_funds():
    return {"funds": data_v2.list_funds(), "default": data_v2.DEFAULT_FUND_ID_V2}


@app.get("/api/fund")
def get_fund(fund_id: str | None = Query(None)):
    ds = _ds(fund_id)
    f = dict(ds["fund"])
    f["aum_cr"] = _to_cr(f["aum"])
    f["holdings_count"] = len(ds["holdings"])
    f["cash_pct"] = round(ds["cash"]["total_cash"] / f["aum"] * 100, 2)
    return f


@app.post("/api/fund/save")
def save_fund(fund_id: str | None = Query(None)):
    """Persist the current fund dataset to the database."""
    ds = _ds(fund_id)
    if db.save_fund_dataset(ds["id"], ds):
        return {"status": "saved", "fund_id": ds["id"]}
    raise HTTPException(status_code=503, detail="Fund data persistence unavailable")


@app.get("/api/holdings")
def get_holdings(fund_id: str | None = Query(None)):
    ds = _ds(fund_id)
    rows = [{**h, "market_value_cr": _to_cr(h["market_value"]),
             "has_lock_in": h["locked_shares"] > 0} for h in ds["holdings"]]
    return {"as_of": data_v2.TODAY.isoformat(), "count": len(rows), "holdings": rows}


@app.get("/api/sector-exposure")
def get_sector_exposure(fund_id: str | None = Query(None)):
    ds = _ds(fund_id)
    sectors: dict[str, float] = {}
    for h in ds["holdings"]:
        sectors[h["sector"]] = sectors.get(h["sector"], 0.0) + h["weight"]
    rows = [{"sector": s, "weight": round(w, 2)}
            for s, w in sorted(sectors.items(), key=lambda kv: kv[1], reverse=True)]
    return {"sectors": rows}


@app.get("/api/cash")
def get_cash(fund_id: str | None = Query(None)):
    ds = _ds(fund_id)
    c, aum = ds["cash"], ds["aum"]
    return {**c, "total_cash_cr": _to_cr(c["total_cash"]), "reserves_cr": _to_cr(c["reserves"]),
            "cash_pct": round(c["total_cash"] / aum * 100, 2),
            "reserves_pct": round(c["reserves"] / aum * 100, 2)}


def _trade_rows(trades):
    return [{**t, "gross_value_cr": _to_cr(t["gross_value"]),
             "cash_impact_cr": _to_cr(t["cash_impact"])} for t in trades]


@app.get("/api/pending-trades")
def get_pending_trades(fund_id: str | None = Query(None)):
    ds = _ds(fund_id)
    rows = _trade_rows(ds["pending_trades"])
    net = sum(t["cash_impact"] for t in ds["pending_trades"])
    cycles: dict[str, dict] = {}
    for t in ds["pending_trades"]:
        c = cycles.setdefault(t["cycle"], {"cycle": t["cycle"], "count": 0, "net": 0.0})
        c["count"] += 1
        c["net"] += t["cash_impact"]
    cycle_rows = [{"cycle": c["cycle"], "count": c["count"], "net_cr": _to_cr(c["net"])}
                  for c in sorted(cycles.values(), key=lambda x: x["cycle"])]
    return {"count": len(rows), "net_cash_impact_cr": _to_cr(net), "by_cycle": cycle_rows, "trades": rows}


@app.get("/api/executed-trades")
def get_executed_trades(fund_id: str | None = Query(None)):
    ds = _ds(fund_id)
    rows = _trade_rows(ds["executed_trades"])
    net = sum(t["cash_impact"] for t in ds["executed_trades"])
    return {"count": len(rows), "net_cash_impact_cr": _to_cr(net), "trades": rows}


@app.get("/api/corporate-actions")
def get_corporate_actions(fund_id: str | None = Query(None)):
    ds = _ds(fund_id)
    rows = [{**ca, "cash_amount_cr": _to_cr(ca["cash_amount"])} for ca in ds["corporate_actions"]]
    total = sum(ca["cash_amount"] for ca in ds["corporate_actions"])
    return {"count": len(rows), "total_cr": _to_cr(total), "actions": rows}


@app.get("/api/compliance-limits")
def get_compliance_limits(fund_id: str | None = Query(None)):
    ds = _ds(fund_id)
    compliance_mod = data_v2 if ds["id"] in data_v2.FUNDS_V2 else data
    limits = compliance_mod.get_fund_compliance_limits(ds["id"]) if hasattr(compliance_mod, "get_fund_compliance_limits") else compliance_mod.COMPLIANCE_LIMITS
    return {"limits": limits, "utilization": compliance_mod.compliance_utilization(ds)}


@app.get("/api/fund-expense")
def get_fund_expense(fund_id: str | None = Query(None)):
    ds = _ds(fund_id)
    e = ds["fund_expense"]
    return {"expense_ratio": e["expense_ratio"], "annual_expense_cr": _to_cr(e["annual_expense"]),
            "daily_accrual_cr": round(e["daily_accrual"] / data_v2.CRORE, 4),
            "monthly_accrual_cr": _to_cr(e["monthly_accrual"]),
            "components": [{"component": c["component"], "bps": c["bps"],
                            "annual_amount_cr": _to_cr(c["annual_amount"])} for c in e["components"]]}


@app.get("/api/lock-ins")
def get_lock_ins(fund_id: str | None = Query(None)):
    ds = _ds(fund_id)
    rows = [{"ticker": h["ticker"], "name": h["name"], "locked_shares": h["locked_shares"],
             "locked_value_cr": _to_cr(h["locked_shares"] * h["price"]),
             "lock_in_expiry": h["lock_in_expiry"], "lock_in_reason": h["lock_in_reason"]}
            for h in ds["holdings"] if h["locked_shares"] > 0]
    return {"count": len(rows), "lock_ins": rows}


@app.get("/api/event-calendar")
def get_event_calendar(fund_id: str | None = Query(None)):
    ds = _ds(fund_id)
    return {"events": ds["event_calendar"]}


@app.get("/api/universe")
def get_universe():
    return {"universe": []}


@app.get("/api/risk-return")
def get_risk_return(fund_id: str | None = Query(None)):
    """Fund-level synthetic risk/return point + curated strategy mandate band,
    plus per-holding stock-level risk/return metrics, for the risk/return
    graph and slider. See docs/nav-risk-return-metrics.md and
    docs/data-v2-real-vs-curated.md."""
    ds = _ds(fund_id)
    fund_metrics = db.get_fund_risk_return_metrics(ds["id"])
    isins = [h["isin"] for h in ds["holdings"] if h.get("isin")]
    stock_metrics = db.get_stock_risk_return_metrics(isins) or {}
    stocks = []
    for h in ds["holdings"]:
        m = stock_metrics.get(h.get("isin"))
        if not m:
            continue
        stocks.append({
            "ticker": h["ticker"], "name": h["name"], "sector": h["sector"], "weight": h["weight"],
            "annualized_return": m["annualized_return"], "annualized_volatility": m["annualized_volatility"],
            "sharpe_ratio": m["sharpe_ratio"], "sortino_ratio": m["sortino_ratio"],
        })
    historical = planner._estimate_post_trade_risk_return(ds, [], None, "rebalance", 0.0)
    return {
        "fund": fund_metrics,
        "stocks": stocks,
        "historical_portfolio": {
            "annualized_return": historical["fund_current_annualized_return"],
            "annualized_volatility": historical["fund_current_annualized_volatility"],
        },
    }


# --------------------------------------------------------------------------- #
# Trade-plan generation & PIC review
# --------------------------------------------------------------------------- #
def _load_plan(plan_id: str) -> dict | None:
    """Fetch a plan, DB first (source of truth once a decision has been made —
    see ``decide_trade_plan``, which is the only place a plan is written to the
    DB). A plan with no decision yet is never in the DB, so the in-memory cache
    is the fallback for that case; it's also the only source when the DB itself
    is unreachable. It is never used to resurrect a since-decided plan after a
    reseed/reset, since a decided plan is always in the DB and a reset clears
    the in-memory cache too (see ``reset_database``)."""
    if db.available():
        plan = db.get_plan(plan_id)
        if plan is not None:
            return plan
    return _PLANS.get(plan_id)


@app.post("/api/trade-plan")
def create_trade_plan(req: IntentRequest, fund_id: str | None = Query(None)):
    plan = planner.generate_plan(fund_id or req.fund_id, req.model_dump(exclude={"fund_id"}))
    _PLANS[plan["plan_id"]] = plan   # in-memory only until a PIC decision is recorded
    return plan


# Each granular step is real backend work, but generation is sub-second, so we
# linger on every emitted step for a randomised 1-3s. This keeps each real
# output readable and gives the stream a natural, non-mechanical cadence.
_STEP_DWELL_MIN_SECONDS = 0.0
_STEP_DWELL_MAX_SECONDS = 0.1


@app.post("/api/trade-plan/stream")
async def create_trade_plan_stream(req: IntentRequest, fund_id: str | None = Query(None)):
    """Generate a plan, streaming real per-phase progress as Server-Sent Events.

    Emits a ``progress`` event as each planning phase actually completes (with
    real computed values), then a final ``plan`` event carrying the full plan.
    Errors surface as an ``error`` event instead of a 500 so the UI can react.
    """
    intent = req.model_dump(exclude={"fund_id"})
    resolved_fund = fund_id or req.fund_id

    async def event_source():
        try:
            for event in planner.iter_plan_steps(resolved_fund, intent):
                if event.get("type") == "plan":
                    plan = event["plan"]
                    _PLANS[plan["plan_id"]] = plan   # in-memory only until a PIC decision is recorded
                    yield {"event": "plan", "data": json.dumps(plan)}
                else:
                    yield {"event": "progress", "data": json.dumps(event)}
                    # Let the completed step stay on screen for a random beat.
                    await asyncio.sleep(random.uniform(
                        _STEP_DWELL_MIN_SECONDS, _STEP_DWELL_MAX_SECONDS))
        except Exception as exc:  # surface failures to the client stream
            yield {"event": "error", "data": json.dumps({"message": str(exc)})}

    return EventSourceResponse(event_source())


@app.get("/api/trade-plans")
def list_trade_plans(fund_id: str | None = Query(None)):
    # db.list_plans() returns None only when the DB is unreachable, and [] when
    # it's reachable but has no rows (e.g. right after init_db.py --reset) — the
    # two must stay distinguishable so a reset doesn't get backfilled by stale
    # in-memory plans from before the reset.
    plans = db.list_plans(fund_id)
    if plans is None:
        # DB unreachable: in-memory cache is the only thing we have. Only plans
        # with a recorded decision count as "history" (matches the DB path).
        plans = [
            plan for plan in _PLANS.values()
            if plan.get("decision") and (fund_id is None or plan.get("fund", {}).get("fund_id") == fund_id)
        ]
    ordered = sorted(plans, key=lambda plan: plan.get("created_at") or "", reverse=True)
    email_summaries = db.list_sent_email_summaries() or {}
    ordered = [
        {
            **plan,
            **email_summaries.get(plan.get("plan_id"), {
                "sent_email_count": 0,
                "last_sent_email_at": None,
            }),
        }
        for plan in ordered
    ]
    return {"plans": ordered, "count": len(ordered)}


@app.get("/api/trade-plan/{plan_id}")
def get_trade_plan(plan_id: str):
    plan = _load_plan(plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    return plan


@app.post("/api/assistant/interpret")
def interpret_trade_intent(req: AssistantInterpretRequest):
    funds = data_v2.list_funds()
    sectors = set(data.BUY_ALLOCATION)
    securities = {security["ticker"] for security in data.UNIVERSE}
    for fund in funds:
        dataset = data_v2.get_ds(fund["fund_id"])
        sectors.update(
            holding.get("sector") for holding in dataset["holdings"] if holding.get("sector")
        )
        securities.update(holding["ticker"] for holding in dataset["holdings"] if holding.get("ticker"))
    try:
        return assistant.interpret_intent(
            req.message,
            req.draft,
            funds,
            sorted(sectors),
            sorted(securities),
        )
    except assistant.AssistantConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except assistant.AssistantGenerationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/trade-plan/{plan_id}/assistant-chat", response_model=AssistantChatResponse)
def chat_about_trade_plan(plan_id: str, req: AssistantChatRequest):
    plan = _load_plan(plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    try:
        result = assistant.chat_about_plan(
            req.message,
            [item.model_dump() for item in req.history],
            plan,
        )
    except assistant.AssistantConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except assistant.AssistantGenerationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return AssistantChatResponse(plan_id=plan_id, **result.model_dump())


@app.post("/api/trade-plan/{plan_id}/email-draft", response_model=EmailDraftResponse)
def generate_trade_plan_email(plan_id: str):
    plan = _load_plan(plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    decision = (plan.get("decision") or {}).get("decision")
    decision = decision or ("Approve" if str(plan.get("status", "")).lower().startswith("approved") else None)
    if decision not in {"Approve", "Reject", "Escalate"}:
        raise HTTPException(status_code=409, detail="Email drafts are available after approval, rejection, or escalation")
    try:
        draft = email_draft.generate_email_template(plan)
    except email_draft.EmailDraftConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except email_draft.EmailDraftGenerationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return EmailDraftResponse(plan_id=plan_id, **draft)


@app.post("/api/trade-plan/{plan_id}/emails/send", response_model=SentEmailResponse)
def send_trade_plan_email(plan_id: str, content: SendEmailRequest):
    plan = _load_plan(plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    decision = (plan.get("decision") or {}).get("decision")
    decision = decision or ("Approve" if str(plan.get("status", "")).lower().startswith("approved") else None)
    if decision not in {"Approve", "Reject", "Escalate"}:
        raise HTTPException(status_code=409, detail="Emails can be sent after approval, rejection, or escalation")
    sent_at = datetime.now(timezone.utc).isoformat()
    sent_email = db.create_sent_email({
        "plan_id": plan_id,
        "email_id": str(uuid4()),
        **content.model_dump(),
        "sent_at": sent_at,
    })
    if sent_email is None:
        raise HTTPException(status_code=503, detail="Sent email storage is unavailable")
    return SentEmailResponse(**sent_email)


@app.get("/api/trade-plan/{plan_id}/emails")
def list_trade_plan_sent_emails(plan_id: str):
    if not _load_plan(plan_id):
        raise HTTPException(status_code=404, detail="Plan not found")
    emails = db.list_sent_emails(plan_id)
    if emails is None:
        raise HTTPException(status_code=503, detail="Sent email storage is unavailable")
    return {"plan_id": plan_id, "emails": emails}


@app.post("/api/trade-plan/{plan_id}/decision", response_model=DecisionResponse)
def decide_trade_plan(plan_id: str, req: DecisionRequest):
    plan = _load_plan(plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    status_map = {
        "Approve": "Approved — sent to Trading",
        "Reject": "Rejected", "Escalate": "Escalated to PIC Lead / PM",
    }
    new_status = status_map[req.decision]
    decided_at = datetime.now(timezone.utc).isoformat()
    decision = {"decision": req.decision, "reviewer": req.reviewer,
                "comment": req.comment, "decided_at": decided_at}
    plan["status"] = new_status
    plan["decision"] = decision
    if plan_id in _PLANS:
        _PLANS[plan_id] = plan
    # A plan only enters the DB (i.e. plan history) once a PIC decision is made —
    # save_plan() here is this plan's first-ever DB write, carrying the decision
    # already merged in. save_decision() then also appends the plan_decisions
    # audit row (a no-op update of the row save_plan just wrote otherwise).
    db.save_plan(plan)
    db.save_decision(plan_id, new_status, decision)   # persist (no-op if DB absent)
    return DecisionResponse(plan_id=plan_id, status=new_status, decision=req.decision,
                            reviewer=req.reviewer, comment=req.comment, decided_at=decided_at)
