# PIC Trade-Plan Studio

A working demo of the **Portfolio Implementation & Control (PIC)** automation
concept ("WealthVector") — the intelligent **middle layer** that turns a Portfolio
Manager's investment intent into a review-ready **trading plan** in minutes
instead of hours.

> **Recommends, does not decide.** The engine generates the plan; a PIC
> associate approves / modifies / rejects / escalates it. Investment decisions
> stay with the PM; operational control stays with PIC.

See [docs/trade-plan-data-requirements.md](docs/trade-plan-data-requirements.md)
for the data model this is built on.

## What it demonstrates

Using a synthetic snapshot of a popular India large-cap fund
(**HDFC Top 100 Fund**, illustrative):

1. **PM Intent** — e.g. *"Increase Technology allocation by ₹50 Cr."*
2. **Cash-flow planning** — how much cash is truly investable after reserves,
   pending settlements, dividend inflows and expense accruals.
3. **Trade-plan generation** — dollars → share-level buy/sell orders, with
   funding sources (trims holdings if cash is short).
4. **Compliance checks** — SEBI-style single-issuer, sector and group limits.
5. **Risk flags** — lock-ins, liquidity / market impact, event-timing risk.
6. **PIC review** — human approves / modifies / rejects / escalates.

## Project structure

```
PIC/
├── backend/     FastAPI — synthetic data + trade-plan engine   (see backend/README.md)
├── frontend/    React (Vite) — dashboard + trade planner        (see frontend/README.md)
├── docs/        Requirements & design notes
└── misc/        Source diagram & write-up
```

## Quick start

Run the two services in separate terminals.

### 1. Backend (http://localhost:8000)

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate        # Windows  (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

### 2. Frontend (http://localhost:5173)

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. The Vite dev server proxies `/api` to the backend,
so no extra config is needed.

## Notes

- All data is **synthetic and for demonstration only** — not investment advice.
- Each plan can be built three ways, chosen per request (a toggle in the UI):
  - **Manual** — select securities or sectors, choose BUY/SELL where applicable, and enter an amount for each selection.
  - **Rules-Based** — deterministic drift/target heuristics (the original engine).
  - **Convex Optimization** — a forecast-driven CVXPY optimizer decides the
    allocation using predicted 1-month returns, then the **same** compliance and
    risk rules run on the result.
    Convex Optimization is the default; Manual and Rules-Based remain available as explicit choices.
- The return forecast is currently a **placeholder** ([backend/app/forecast.py](backend/app/forecast.py))
  returning dummy expected returns in the shape the production TFT model will
  produce; swap in the real model without touching the rest of the app. The
  convex engine ([backend/app/optimizer.py](backend/app/optimizer.py)) is adapted
  from the `mozart` prototype. Data and models are pluggable — this scaffold is
  the starting point.
