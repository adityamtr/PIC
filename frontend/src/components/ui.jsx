import { Box, Card, CardContent, Stack, Typography } from '@mui/material'
import { BRAND_GRADIENT } from '../theme'

// Auto-fitting KPI row — tiles flow and wrap to fill the available width
// instead of being pinned to a fixed count, so the layout adapts to the page.
export function KpiGrid({ children, min = 200, sx }) {
  return (
    <Box sx={{ display: 'grid', gap: 2,
      gridTemplateColumns: `repeat(auto-fit, minmax(min(100%, ${min}px), 1fr))`, ...sx }}>
      {children}
    </Box>
  )
}

// A single KPI tile. `accent` draws the brand gradient rail to flag the
// headline metric among its peers.
export function Stat({ label, value, sub, color, accent, icon }) {
  return (
    <Card sx={{
      position: 'relative', overflow: 'hidden',
      ...(accent && {
        '&::before': {
          content: '""', position: 'absolute', left: 0, top: 0, bottom: 0,
          width: 4, background: BRAND_GRADIENT,
        },
      }),
    }}>
      <CardContent sx={{ py: 1.75, pl: accent ? 2.5 : 2 }}>
        <Stack direction="row" alignItems="center" justifyContent="space-between" spacing={1}>
          <Typography variant="caption" color="text.secondary"
            sx={{ minWidth: 0, textTransform: 'uppercase', fontWeight: 600 }}>
            {label}
          </Typography>
          {icon && <Box aria-hidden="true" sx={{
            width: 30, height: 30, flexShrink: 0, display: 'grid', placeItems: 'center',
            borderRadius: 1, color: color || 'primary.main', bgcolor: 'action.hover',
            '& .MuiSvgIcon-root': { fontSize: 18 },
          }}>{icon}</Box>}
        </Stack>
        <Typography variant="h6" sx={{ color, fontWeight: 700, mt: 0.25, lineHeight: 1.3,
          overflowWrap: 'anywhere', fontVariantNumeric: 'tabular-nums' }}>{value}</Typography>
        {sub && <Typography variant="caption" color="text.secondary">{sub}</Typography>}
      </CardContent>
    </Card>
  )
}

// A titled panel used across the bento layouts. `highlight` adds a gradient
// top-rail and a stronger shadow so the most important section on a page pulls
// the eye. It stretches to fill its grid cell (height 100%).
export function Panel({ title, subtitle, action, highlight, icon, sx, bodySx, children }) {
  return (
    <Card sx={{
      height: '100%', display: 'flex', flexDirection: 'column', overflow: 'hidden',
      ...(highlight && {
        boxShadow: '0 2px 6px rgba(16,24,64,0.07), 0 18px 44px rgba(99,102,241,0.14)',
      }),
      ...sx,
    }}>
      {highlight && <Box sx={{ height: 4, background: BRAND_GRADIENT, flexShrink: 0 }} />}
      <CardContent sx={{ flex: 1, minWidth: 0, ...bodySx }}>
        {(title || action) && (
          <Stack direction="row" alignItems="center" justifyContent="space-between"
            sx={{ mb: subtitle ? 0.25 : 1.5, gap: 1 }}>
            <Stack direction="row" alignItems="center" spacing={0.9} sx={{ minWidth: 0, flex: 1 }}>
              {icon && <Box aria-hidden="true" sx={{
                width: 28, height: 28, flexShrink: 0, display: 'grid', placeItems: 'center',
                borderRadius: 1, color: 'primary.main', bgcolor: 'action.hover',
                '& .MuiSvgIcon-root': { fontSize: 18 },
              }}>{icon}</Box>}
              <Typography variant="subtitle2" color="text.secondary"
                sx={{ minWidth: 0, textTransform: 'uppercase', lineHeight: 1.35 }}>{title}</Typography>
            </Stack>
            {action}
          </Stack>
        )}
        {subtitle && (
          <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1.5 }}>
            {subtitle}
          </Typography>
        )}
        {children}
      </CardContent>
    </Card>
  )
}

// Horizontal-scroll wrapper so wide tables stay usable inside narrower grid
// cells without breaking the layout.
export function ScrollX({ children, maxHeight }) {
  return <Box sx={{ overflowX: 'auto', ...(maxHeight && { maxHeight, overflowY: 'auto' }) }}>{children}</Box>
}
