import { useState } from 'react'
import { Box, Stack, Typography, useTheme } from '@mui/material'
import { fmtPct } from '../format'

// Validated categorical palette (dataviz skill, adjacent-pair CVD-safe in both
// modes). Light mode flags a contrast WARN on aqua/yellow/magenta — covered by
// the relief rule: visible direct labels (the legend) + 2px surface gaps.
const HUES = {
  light: ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300'],
  dark: ['#3987e5', '#d95926', '#199e70', '#c98500', '#d55181', '#008300'],
}
const OTHER = '#898781' // muted gray — the tail is not a real category
const CAP = 6

// Annulus (donut) segment path.
function arc(cx, cy, rO, rI, a0, a1) {
  const pt = (r, a) => [cx + r * Math.cos(a), cy + r * Math.sin(a)]
  const large = a1 - a0 > Math.PI ? 1 : 0
  const [x0, y0] = pt(rO, a0)
  const [x1, y1] = pt(rO, a1)
  const [x2, y2] = pt(rI, a1)
  const [x3, y3] = pt(rI, a0)
  return `M${x0} ${y0} A${rO} ${rO} 0 ${large} 1 ${x1} ${y1} `
    + `L${x2} ${y2} A${rI} ${rI} 0 ${large} 0 ${x3} ${y3} Z`
}

export default function SectorDonut({ sectors }) {
  const theme = useTheme()
  const mode = theme.palette.mode
  const surface = theme.palette.background.paper
  const [hover, setHover] = useState(null)

  // Fold a long tail into "Other" so we never exceed the categorical ceiling.
  let rows = sectors
  if (sectors.length > CAP) {
    const head = sectors.slice(0, CAP - 1)
    const tailWeight = sectors.slice(CAP - 1).reduce((s, r) => s + r.weight, 0)
    rows = [...head, { sector: 'Other', weight: Number(tailWeight.toFixed(2)) }]
  }
  const colorFor = (r, i) => (r.sector === 'Other' ? OTHER : HUES[mode][i])

  const total = rows.reduce((s, r) => s + r.weight, 0)
  const size = 220, cx = 110, cy = 110, rO = 96, rI = 62
  let a = -Math.PI / 2
  const segs = rows.map((r, i) => {
    const a0 = a
    const a1 = a0 + (r.weight / total) * 2 * Math.PI
    a = a1
    return { ...r, a0, a1, color: colorFor(r, i), i }
  })

  const active = hover != null ? segs[hover] : null

  return (
    <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} alignItems="center">
      <Box sx={{ position: 'relative', flexShrink: 0 }}>
        <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img"
          aria-label="Sector exposure by weight">
          {segs.map((s) => (
            <path key={s.sector} d={arc(cx, cy, rO, rI, s.a0, s.a1)}
              fill={s.color} stroke={surface} strokeWidth={2} strokeLinejoin="round"
              onMouseEnter={() => setHover(s.i)} onMouseLeave={() => setHover(null)}
              style={{
                cursor: 'default',
                opacity: hover == null || hover === s.i ? 1 : 0.4,
                transition: 'opacity .15s ease',
              }} />
          ))}
        </svg>
        {/* Center label — total equities, or the hovered sector */}
        <Box sx={{ position: 'absolute', inset: 0, display: 'grid', placeItems: 'center',
          pointerEvents: 'none', textAlign: 'center', px: 3 }}>
          <Box>
            <Typography variant="h5" fontWeight={800} lineHeight={1.1}
              sx={{ color: active ? active.color : 'text.primary' }}>
              {fmtPct(active ? active.weight : total)}
            </Typography>
            <Typography variant="caption" color="text.secondary"
              sx={{ display: 'block', maxWidth: 96, mx: 'auto' }}>
              {active ? active.sector : 'in equities'}
            </Typography>
          </Box>
        </Box>
      </Box>

      {/* Legend — direct labels satisfy the relief rule and carry identity */}
      <Stack spacing={0.5} sx={{ minWidth: 0, flexGrow: 1, alignSelf: 'stretch', justifyContent: 'center' }}>
        {segs.map((s) => (
          <Stack key={s.sector} direction="row" alignItems="center" spacing={1}
            onMouseEnter={() => setHover(s.i)} onMouseLeave={() => setHover(null)}
            sx={{ py: 0.25, borderRadius: 1, cursor: 'default',
              opacity: hover == null || hover === s.i ? 1 : 0.5, transition: 'opacity .15s ease' }}>
            <Box sx={{ width: 10, height: 10, borderRadius: '3px', bgcolor: s.color, flexShrink: 0 }} />
            <Typography variant="body2" sx={{ flexGrow: 1, minWidth: 0, overflow: 'hidden',
              textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {s.sector}
            </Typography>
            <Typography variant="body2" color="text.secondary"
              sx={{ fontVariantNumeric: 'tabular-nums' }}>
              {fmtPct(s.weight)}
            </Typography>
          </Stack>
        ))}
      </Stack>
    </Stack>
  )
}
