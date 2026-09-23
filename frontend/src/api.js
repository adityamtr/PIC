// Thin API client for the PIC Trade-Plan backend (multi-fund).
// In dev, Vite proxies /api -> http://localhost:8000 (see vite.config.js).

const BASE = '/api'

function qs(fundId) {
  return fundId ? `?fund_id=${encodeURIComponent(fundId)}` : ''
}

async function get(path) {
  const res = await fetch(`${BASE}${path}`)
  if (!res.ok) throw new Error(`GET ${path} -> ${res.status}`)
  return res.json()
}

async function post(path, body) {
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    const detail = await res.text()
    throw new Error(`POST ${path} -> ${res.status}: ${detail}`)
  }
  return res.json()
}

export const api = {
  health: () => get('/health'),
  funds: () => get('/funds'),
  fund: (fundId) => get(`/fund${qs(fundId)}`),
  holdings: (fundId) => get(`/holdings${qs(fundId)}`),
  sectorExposure: (fundId) => get(`/sector-exposure${qs(fundId)}`),
  universe: () => get('/universe'),
  cash: (fundId) => get(`/cash${qs(fundId)}`),
  pendingTrades: (fundId) => get(`/pending-trades${qs(fundId)}`),
  executedTrades: (fundId) => get(`/executed-trades${qs(fundId)}`),
  corporateActions: (fundId) => get(`/corporate-actions${qs(fundId)}`),
  complianceLimits: (fundId) => get(`/compliance-limits${qs(fundId)}`),
  fundExpense: (fundId) => get(`/fund-expense${qs(fundId)}`),
  lockIns: (fundId) => get(`/lock-ins${qs(fundId)}`),
  eventCalendar: (fundId) => get(`/event-calendar${qs(fundId)}`),
  createTradePlan: (intent) => post('/trade-plan', intent),
  decide: (planId, decision) => post(`/trade-plan/${planId}/decision`, decision),
}
