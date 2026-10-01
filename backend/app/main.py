"""
PIC Trade-Plan API (FastAPI), multi-fund.

Exposes synthetic portfolio data and the trade-plan generation engine. This is
the automated "middle layer": it converts a PM's intent into a review-ready
trading plan. A PIC associate approves it. Recommends — does not decide.

Most read endpoints accept an optional `?fund_id=` query parameter; when omitted
the default fund is used.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from . import data_v2, db, email_draft, forecast, planner
from .schemas import DecisionRequest, DecisionResponse, EmailDraftResponse, IntentRequest

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


def _to_cr(value):
    return round(value / data_v2.CRORE, 2)


def _ds(fund_id):
    return data_v2.get_ds(fund_id)


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


# --------------------------------------------------------------------------- #
# Trade-plan generation & PIC review
# --------------------------------------------------------------------------- #
def _load_plan(plan_id: str) -> dict | None:
    """Fetch a plan from the DB, falling back to the in-memory cache."""
    return db.get_plan(plan_id) or _PLANS.get(plan_id)


@app.post("/api/trade-plan")
def create_trade_plan(req: IntentRequest, fund_id: str | None = Query(None)):
    plan = planner.generate_plan(fund_id or req.fund_id, req.model_dump(exclude={"fund_id"}))
    _PLANS[plan["plan_id"]] = plan   # in-memory cache (fallback when DB is absent)
    db.save_plan(plan)               # persist to SQLite (no-op if DB unavailable)
    return plan


@app.get("/api/trade-plans")
def list_trade_plans(fund_id: str | None = Query(None)):
    plans = db.list_plans(fund_id)
    by_id = {plan["plan_id"]: plan for plan in (plans or []) if plan.get("plan_id")}
    by_id.update({
        plan_id: plan for plan_id, plan in _PLANS.items()
        if fund_id is None or plan.get("fund", {}).get("fund_id") == fund_id
    })
    ordered = sorted(by_id.values(), key=lambda plan: plan.get("created_at") or "", reverse=True)
    return {"plans": ordered, "count": len(ordered)}


@app.get("/api/trade-plan/{plan_id}")
def get_trade_plan(plan_id: str):
    plan = _load_plan(plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    return plan


@app.post("/api/trade-plan/{plan_id}/email-draft", response_model=EmailDraftResponse)
def generate_trade_plan_email(plan_id: str):
    plan = _load_plan(plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    decision = (plan.get("decision") or {}).get("decision")
    is_approved = decision == "Approve" if decision else str(plan.get("status", "")).lower().startswith("approved")
    if not is_approved:
        raise HTTPException(status_code=409, detail="Email drafts are available only for approved plans")
    try:
        draft = email_draft.generate_email_template(plan)
    except email_draft.EmailDraftConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except email_draft.EmailDraftGenerationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return EmailDraftResponse(plan_id=plan_id, **draft)


@app.post("/api/trade-plan/{plan_id}/decision", response_model=DecisionResponse)
def decide_trade_plan(plan_id: str, req: DecisionRequest):
    plan = _load_plan(plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    status_map = {
        "Approve": "Approved — sent to Trading", "Modify": "Returned for Modification",
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
    db.save_decision(plan_id, new_status, decision)   # persist (no-op if DB absent)
    return DecisionResponse(plan_id=plan_id, status=new_status, decision=req.decision,
                            reviewer=req.reviewer, comment=req.comment, decided_at=decided_at)
