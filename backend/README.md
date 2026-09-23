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
| `app/planner.py` | Cash-flow planning, funding, order generation, compliance checks, risk flags, recommendation. |
| `app/schemas.py` | Pydantic request/response models. |
| `app/main.py` | FastAPI app & routes. |

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
curl -X POST http://localhost:8000/api/trade-plan \
  -H "Content-Type: application/json" \
  -d '{"action":"increase","target":"Technology","amount_cr":50,"horizon_days":5}'
```
