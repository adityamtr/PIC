// Thin API client for the PIC Trade-Plan backend (multi-fund).
// In dev, Vite proxies /api -> http://localhost:8000 (see vite.config.js).

const BASE = '/api'

function qs(fundId) {
  return fundId ? `?fund_id=${encodeURIComponent(fundId)}` : ''
}

async function get(path) {
  const res = await fetch(`${BASE}${path}`, { cache: 'no-store' })
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

// Parse a single raw SSE frame ("event: x\ndata: {...}") into {event, data}.
function parseSseFrame(raw) {
  let event = 'message'
  const dataLines = []
  for (const line of raw.split('\n')) {
    if (line.startsWith('event:')) event = line.slice(6).trim()
    else if (line.startsWith('data:')) dataLines.push(line.slice(5).replace(/^ /, ''))
  }
  if (!dataLines.length) return null
  return { event, data: dataLines.join('\n') }
}

// POST that consumes a text/event-stream response. The browser's native
// EventSource only supports GET, so we read the body stream with fetch and
// parse SSE frames by hand. `onEvent({event, data})` fires per frame.
async function postStream(path, body, { onEvent, signal } = {}) {
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify(body),
    signal,
  })
  if (!res.ok || !res.body) {
    const detail = res.body ? await res.text() : ''
    throw new Error(`POST ${path} -> ${res.status}: ${detail}`)
  }
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  const flush = (frame) => {
    const evt = parseSseFrame(frame)
    if (evt) onEvent?.(evt)
  }
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    buffer = buffer.replace(/\r\n/g, '\n')
    let sep
    while ((sep = buffer.indexOf('\n\n')) !== -1) {
      flush(buffer.slice(0, sep))
      buffer = buffer.slice(sep + 2)
    }
  }
  if (buffer.trim()) flush(buffer)
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
  riskReturn: (fundId) => get(`/risk-return${qs(fundId)}`),
  createTradePlan: (intent) => post('/trade-plan', intent),
  interpretIntent: (request) => post('/assistant/interpret', request),
  assistantChat: (planId, message, history) => post(
    `/trade-plan/${encodeURIComponent(planId)}/assistant-chat`,
    { message, history },
  ),
  // Streaming variant: emits real per-phase progress via `onProgress`, resolves
  // with the finished plan. Falls back to throwing on an `error` event.
  createTradePlanStream: async (intent, { onProgress, signal } = {}) => {
    let plan = null
    let streamError = null
    await postStream('/trade-plan/stream', intent, {
      signal,
      onEvent: ({ event, data }) => {
        let payload
        try { payload = JSON.parse(data) } catch { return }
        if (event === 'progress') onProgress?.(payload)
        else if (event === 'plan') plan = payload
        else if (event === 'error') streamError = new Error(payload.message || 'Plan generation failed.')
      },
    })
    if (streamError) throw streamError
    if (!plan) throw new Error('Plan stream ended without a plan.')
    return plan
  },
  tradePlans: (fundId) => get(`/trade-plans${qs(fundId)}`),
  generatePlanEmail: (planId) => post(`/trade-plan/${encodeURIComponent(planId)}/email-draft`, {}),
  sendPlanEmail: (planId, content) => post(
    `/trade-plan/${encodeURIComponent(planId)}/emails/send`,
    content,
  ),
  planSentEmails: (planId) => get(`/trade-plan/${encodeURIComponent(planId)}/emails`),
  decide: (planId, decision) => post(`/trade-plan/${planId}/decision`, decision),
  resetDb: () => post('/admin/reset-db', {}),
}
