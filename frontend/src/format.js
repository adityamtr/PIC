// Formatting helpers (Indian number system).

export function fmtCr(valueRupees, digits = 2) {
  if (valueRupees == null) return '—'
  const cr = valueRupees / 1e7
  return `₹${cr.toLocaleString('en-IN', { maximumFractionDigits: digits, minimumFractionDigits: digits })} Cr`
}

// For values already expressed in crore.
export function fmtCrValue(cr, digits = 2) {
  if (cr == null) return '—'
  const sign = cr < 0 ? '-' : ''
  return `${sign}₹${Math.abs(cr).toLocaleString('en-IN', { maximumFractionDigits: digits, minimumFractionDigits: digits })} Cr`
}

export function fmtNum(n) {
  if (n == null) return '—'
  return n.toLocaleString('en-IN')
}

export function fmtPct(p, digits = 2) {
  if (p == null) return '—'
  return `${p.toFixed(digits)}%`
}

export function fmtRupee(n, digits = 2) {
  if (n == null) return '—'
  return `₹${n.toLocaleString('en-IN', { maximumFractionDigits: digits, minimumFractionDigits: digits })}`
}

export function statusClass(status) {
  const s = (status || '').toUpperCase()
  if (s === 'PASS' || s === 'OK') return 'badge badge-ok'
  if (s === 'WARN' || s === 'MEDIUM') return 'badge badge-warn'
  if (s === 'FAIL' || s === 'BREACH' || s === 'HIGH') return 'badge badge-fail'
  return 'badge'
}
