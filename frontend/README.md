# PIC Trade-Plan UI (frontend)

React + Vite single-page app for the PIC trade-plan demo.

## Run

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. The backend must be running on
http://localhost:8000 (Vite proxies `/api` to it — see `vite.config.js`).

## Structure

| Path | Purpose |
|------|---------|
| `src/App.jsx` | Shell: workflow ribbon + tabs |
| `src/components/TradePlanner.jsx` | PM intent → plan → PIC review |
| `src/components/Dashboard.jsx` | Portfolio, cash, compliance, lock-ins, expense |
| `src/api.js` | Backend client |
| `src/format.js` | ₹ crore / percent formatting (Indian number system) |
| `src/styles.css` | Theme |

## Two views

- **Trade Planner** — submit an intent (or a preset), see cash-flow planning,
  generated orders, compliance checks and risk flags, then approve / modify /
  reject / escalate.
- **Portfolio Dashboard** — holdings, sector exposure, cash & reserves, pending
  trades, compliance utilisation, lock-ins, corporate actions and fund expense.
