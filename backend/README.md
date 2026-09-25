# PIC Trade-Plan API (backend)

FastAPI service that powers the demo. It exposes the synthetic portfolio dataset
and the trade-plan generation engine — the automated **middle layer** between a
Portfolio Manager's intent and trade execution.

> It **recommends, it does not decide**. Every generated plan comes back as
> `Pending PIC Review` for a human to approve / modify / reject / escalate.

## Run

```bash
cd backend
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
# source .venv/bin/activate

pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

- API root: http://localhost:8000
- Interactive docs (Swagger): http://localhost:8000/docs

## Structure

| File | Responsibility |
|------|----------------|
| `app/data.py` | Synthetic dataset (fund, holdings, cash, pending trades, lock-ins, compliance limits, corporate actions, expense, universe, events). Replace with live feeds later. |
| `app/forecast.py` | **Return-forecasting placeholder** — dummy expected 1-month returns per stock, in the shape the production TFT model will produce. Swap the body of `predict_returns` for real inference later. |
| `app/optimizer.py` | **Convex-optimization engine (CVXPY)**, adapted from the `mozart` prototype: `optimize_buy` / `optimize_sell` / `optimize_rebalance`. Optional dependency — if `cvxpy` is missing the planner falls back to rules. |
| `app/policy.py` | Proposed pre-trade policy evaluator for mandate, liquidity, concentration, corporate-action, restriction, ESG, country, cash-flow, and plan-creation rules. Dummy thresholds are versioned in the generated plan. |
| `app/planner.py` | Cash-flow planning, funding, order generation (rule-based **or** forecast-driven convex optimization), compliance checks, risk flags, recommendation. |
| `app/schemas.py` | Pydantic request/response models. |
| `app/main.py` | FastAPI app & routes. |

## Allocation methods

`POST /api/trade-plan` accepts a `method` field:

- `"optimize"` (default) — `forecast.py` predicts each stock's expected 1-month return and
  `optimizer.py` solves a convex program to choose the allocation (deploy cash into the
  highest-forecast names, raise cash from the lowest-forecast names, and retilt the book
  within issuer + turnover limits).
- `"manual"` — use `manual_selections` to specify each ticker, BUY/SELL side, and amount, or
  `manual_sector_selections` to specify each sector and amount. Sell orders are capped by each
  holding's sellable shares.
- `"rules"` — the original heuristic drift/target logic decides which
  holdings to change.

Either way the **same compliance and risk rules run on the result**, and the
plan still comes back as `Pending PIC Review`. Every plan includes a `forecast`
block (the predicted returns) and, for `optimize`, an `optimization` meta block
(solver, status, objective); every order carries its `expected_return`.

## Key endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/health` | Liveness |
| GET | `/api/fund` | Fund master data |
| GET | `/api/holdings` | Holdings with sector / weight / lock-in |
| GET | `/api/sector-exposure` | Aggregated sector weights |
| GET | `/api/cash` | Cash & reserves |
| GET | `/api/pending-trades` | Unsettled trades |
| GET | `/api/corporate-actions` | Upcoming dividends |
| GET | `/api/compliance-limits` | Limits + current utilisation |
| GET | `/api/fund-expense` | TER breakdown |
| GET | `/api/lock-ins` | Locked positions |
| GET | `/api/event-calendar` | Earnings / ex-dates |
| POST | `/api/trade-plan` | Generate a plan from PM intent |
| POST | `/api/trade-plan/{id}/decision` | Record a PIC decision |

### Example: generate a plan

```bash
# rule-based (default)
curl -X POST http://localhost:8000/api/trade-plan \
  -H "Content-Type: application/json" \
  -d '{"action":"increase","target":"Technology","amount_cr":50,"horizon_days":5}'

# forecast-driven convex optimization
curl -X POST http://localhost:8000/api/trade-plan \
  -H "Content-Type: application/json" \
  -d '{"action":"increase","target":"Technology","amount_cr":50,"method":"optimize"}'
```
