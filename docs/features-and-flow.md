# WealthVector — Features & Overall Flow (current state)

This document describes what the **PIC Trade-Plan Studio ("WealthVector")** demo does
today: the automated **middle layer** that turns a Portfolio Manager's intent
into a review-ready trading plan, while keeping the decision with a human.

> **Recommends, does not decide.** Every generated plan comes back as
> `Pending PIC Review`; a PIC associate approves / modifies / rejects /
> escalates it. Nothing executes automatically.

Related docs: [trade-plan-data-requirements.md](trade-plan-data-requirements.md).

---

## 1. Architecture at a glance

```
┌─────────────────────────┐        HTTP /api        ┌──────────────────────────┐
│  Frontend (React + MUI)  │  ───────────────────▶   │   Backend (FastAPI)      │
│  Vite dev server :5173   │  ◀───────────────────   │   Uvicorn :8000          │
│                          │      (Vite proxies)     │                          │
│  • Trade Planner         │                         │  • data.py   (synthetic) │
│  • Portfolio             │                         │  • planner.py(engine)    │
│  • Trades                │                         │  • main.py   (REST API)  │
│  • Light/Dark + funds    │                         │                          │
└─────────────────────────┘                         └──────────────────────────┘
```

- **Backend:** FastAPI serving synthetic, **multi-fund** portfolio data and a
  rule-based trade-plan engine (cash-flow planning → orders → compliance →
  risk). In-memory plan store.
- **Frontend:** React + **Material UI (MUI)** single-page app with light/dark
  theme, a fund selector, and three tabs.

---

## 2. Funds modelled (synthetic, illustrative)

Two Indian funds with deliberately different profiles. Switchable from the fund
selector in the top bar; the whole app re-scopes to the selected fund.

| Fund | Category | AUM | Holdings | Cash | TER | Benchmark |
|------|----------|-----|----------|------|-----|-----------|
| **HDFC Top 100 Fund** | Large Cap | ~₹33,200 Cr | 31 | ~3.6% | 1.05% | NIFTY 100 TRI |
| **Parag Parikh Flexi Cap Fund** | Flexi Cap | ~₹86,000 Cr | 14 (concentrated) | ~15.7% | 0.63% | NIFTY 500 TRI |

Each fund carries its own holdings, cash & reserves, pending/executed trades,
corporate actions, lock-ins, expense breakdown and event calendar. Adding
another fund is a single entry in `FUND_SPECS` (backend `app/data.py`).

### Data each fund includes
- **Holdings** — ticker, name, sector, business group, price, shares, market
  value, **target weight vs current weight** (with price *drift* so weights
  diverge from target, making rebalancing meaningful), and **lock-in** details.
- **Cash & liquidity** — total cash, reserves (min buffer), cash %.
- **Pending / unsettled trades** — with **T+1 / T+2** settlement cycles.
- **Previously executed (settled) trades**.
- **Corporate actions** — upcoming dividends → forecast cash inflows.
- **Compliance limits** — SEBI-style single-issuer (10%), group (20%), sector
  (35%), with current utilisation.
- **Fund expense** — TER broken into components (management, RTA, custody, etc.).
- **Event calendar** — earnings / ex-dates for execution-timing risk.
- **Investable universe** — eligible buy candidates with liquidity (ADV).

---

## 3. The core flow (PM intent → PIC decision)

```
1. PM Intent                → what the PM wants (action + amount / sector / fund)
        │
2. Cash-Flow Planning       → how much cash is truly investable
        │   (cash − reserves + pending settlements + dividends − expenses ± flows)
3. Trade-Plan Generation    → dollars converted into share-level BUY/SELL orders
        │   (+ funding sources: from cash, or by trimming holdings)
4. Compliance Checks        → SEBI issuer / sector / group limits (current → projected)
        │
5. Execution Risk Flags     → lock-ins, liquidity / market impact, event timing
        │
6. PIC Review               → Approve / Modify / Reject / Escalate  ← human gate
```

Steps 2–5 are automated by the engine; step 6 is always a human decision.

---

## 4. Intent types supported

The planner handles both **portfolio-level** actions (no sector needed) and
**sector-level** actions.

| Action | Needs | What it does |
|--------|-------|--------------|
| **Contribution** | amount | Deploys an inflow: tops up under-weight names toward target, then spreads any remainder pro-rata to target weights. |
| **Redemption** | amount | Raises cash for a payout: trims over-weight names toward target, then pro-rata by weight. Respects lock-ins. |
| **Rebalance** | — | Moves every holding back to target weight (normalised to the invested proportion, so it is ~cash-neutral). |
| **Increase Sector** | sector + amount | Buys a sector across eligible universe names; funds from cash, or trims other holdings if cash is short. |
| **Reduce Sector** | sector + amount | Trims a sector's holdings to reduce exposure. |

Every generated plan returns:
- **Cash-flow planning** line items and the resulting investable amount.
- **Pending / unsettled trades** for the fund (T+1 / T+2) — shown so the
  associate sees committed-but-unsettled cash already reflected in the plan.
- **Funding sources** (cash, contribution inflow, or specific sell trims).
- **Orders** — share-level BUY/SELL with price and estimated value.
- **Compliance checks** — each rule with current → projected weight vs limit and
  a PASS / WARN / FAIL status.
- **Risk flags** — lock-in, liquidity (% of ADV), and event-timing warnings.
- **Summary** — buy/sell totals, net cash impact, overall compliance status.
- **Recommendation** — plain-language guidance (approve / review / modify).
- **Status** — starts at `Pending PIC Review`; updates on the PIC decision.

---

## 5. Frontend features

### Trade Planner (default tab)
- A **stepper** showing the 5-stage flow (Intent → Cash-Flow → Plan →
  Compliance & Risk → PIC Review).
- Intent form: **action toggle** (Contribution / Redemption / Rebalance /
  Increase / Reduce), conditional amount and sector fields, planning horizon,
  and quick **preset chips**.
- Animated results (`Grow` transition): summary stat tiles, a recommendation
  alert, and collapsible **accordions** for cash-flow planning, **pending
  trades**, orders, and compliance & risk — keeping the view uncluttered.
- **PIC review** action bar: Approve / Modify / Reject / Escalate; the decision
  is recorded and reflected in the plan status.

### Portfolio tab
Simplified overview: fund KPIs, sector-exposure bars, top-utilisation
compliance meters, and a compact holdings table (top 10 with "show all").

### Trades tab
Prominent settlement view: **T+1 / T+2 summary cards**, a **pending / unsettled**
table (with cycle chips and colored cash impact), and a **previously executed
(settled)** table.

### Global
- **Light mode by default**, with a dark-mode toggle (persisted to
  `localStorage`).
- **Fresh, bright theme** — indigo → violet → cyan brand gradient, cyan
  secondary; status colors are teal (success), orange (warning), rose (error).
- **Fund selector** in the top bar; an API-connectivity indicator.

---

## 6. Backend API (REST)

Base URL `http://localhost:8000`. Most read endpoints accept an optional
`?fund_id=` (defaults to the default fund). Interactive docs at `/docs`.

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/health` | Liveness |
| GET | `/api/funds` | List available funds + default |
| GET | `/api/fund` | Fund master data |
| GET | `/api/holdings` | Holdings (sector, weight, lock-in) |
| GET | `/api/sector-exposure` | Aggregated sector weights |
| GET | `/api/cash` | Cash & reserves |
| GET | `/api/pending-trades` | Unsettled trades + T+1/T+2 buckets |
| GET | `/api/executed-trades` | Previously settled trades |
| GET | `/api/corporate-actions` | Upcoming dividends |
| GET | `/api/compliance-limits` | Limits + current utilisation |
| GET | `/api/fund-expense` | TER breakdown |
| GET | `/api/lock-ins` | Locked positions |
| GET | `/api/event-calendar` | Earnings / ex-dates |
| GET | `/api/universe` | Eligible buy universe |
| POST | `/api/trade-plan` | Generate a plan from PM intent (`?fund_id` or body `fund_id`) |
| GET | `/api/trade-plan/{id}` | Fetch a generated plan |
| POST | `/api/trade-plan/{id}/decision` | Record a PIC decision |

### Example
```bash
curl -X POST "http://localhost:8000/api/trade-plan?fund_id=PPFAS-FLEXI-DG" \
  -H "Content-Type: application/json" \
  -d '{"action":"contribution","amount_cr":500,"horizon_days":5}'
```

---

## 7. Running the demo

Two terminals (details in the root [README](../README.md) and per-app READMEs).

```bash
# Backend
cd backend
.venv\Scripts\activate           # Windows (macOS/Linux: source .venv/bin/activate)
uvicorn app.main:app --reload --port 8000

# Frontend
cd frontend
npm run dev                       # http://localhost:5173
```

---

## 8. What is deliberately simplified (for now)

- **Data is synthetic** and hard-coded; no live feeds.
- The forecasting and optimisation are **deterministic and rule-based**; the
  production design substitutes ML models (SARIMA / LSTM / TFT) and a convex
  optimizer.
- Plans are stored **in memory** (reset on backend restart).
- **Modify** currently records the decision but does not yet let the associate
  edit order quantities inline.

These are intentional placeholders — data and models are pluggable, and this
scaffold is the starting point for real integration.
