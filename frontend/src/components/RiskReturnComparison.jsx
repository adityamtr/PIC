import { Box, Stack, Typography, useTheme } from '@mui/material'
import { fmtPct } from '../format'

function MetricDonut({ label, before, after, reference }) {
  const theme = useTheme()
  const size = 156, center = size / 2
  const scale = Math.max(Math.abs(before || 0), Math.abs(after || 0), Math.abs(reference || 0), 0.01) * 1.1
  const rings = [
    { name: 'After', value: after, radius: 59, color: theme.palette.secondary.main },
    { name: 'Before', value: before, radius: 42, color: theme.palette.primary.main },
  ]
  const afterText = after == null ? '—' : fmtPct(after * 100, 1)
  const formatValue = (value) => value == null ? '—' : fmtPct(value * 100, 2)

  return (
    <Box sx={{ display: 'grid', gridTemplateColumns: '156px minmax(0, 1fr)', gap: 1.5, alignItems: 'center' }}>
      <Box sx={{ position: 'relative', width: size, height: size, flexShrink: 0 }}>
        <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img"
          aria-label={`${label}: before ${formatValue(before)}, after ${formatValue(after)}`}>
          {rings.map((ring) => {
            const circumference = 2 * Math.PI * ring.radius
            const fraction = ring.value == null ? 0 : Math.min(Math.abs(ring.value) / scale, 1)
            return (
              <g key={ring.name} transform={`rotate(-90 ${center} ${center})`}>
                <circle cx={center} cy={center} r={ring.radius} fill="none"
                  stroke={theme.palette.divider} strokeWidth="10" opacity="0.45" />
                {fraction > 0 && (
                  <circle cx={center} cy={center} r={ring.radius} fill="none"
                    stroke={ring.color} strokeWidth="10" strokeLinecap="round"
                    strokeDasharray={`${circumference * fraction} ${circumference}`} />
                )}
              </g>
            )
          })}
        </svg>
        <Box sx={{ position: 'absolute', inset: 0, display: 'grid', placeContent: 'center', textAlign: 'center' }}>
          <Typography variant="subtitle2" fontWeight={700} sx={{ fontVariantNumeric: 'tabular-nums' }}>
            {afterText}
          </Typography>
          <Typography variant="caption" color="text.secondary">after</Typography>
        </Box>
      </Box>
      <Stack spacing={1} sx={{ minWidth: 0 }}>
        <Typography variant="subtitle2" fontWeight={700}>{label}</Typography>
        {rings.map((ring) => (
          <Stack key={ring.name} direction="row" spacing={0.75} alignItems="center" justifyContent="space-between">
            <Stack direction="row" spacing={0.75} alignItems="center" sx={{ minWidth: 0 }}>
              <Box sx={{ width: 9, height: 9, borderRadius: '50%', bgcolor: ring.color, flexShrink: 0 }} />
              <Typography variant="body2" color="text.secondary">{ring.name}</Typography>
            </Stack>
            <Typography variant="body2" fontWeight={600} sx={{ fontVariantNumeric: 'tabular-nums' }}>
              {formatValue(ring.value)}
            </Typography>
          </Stack>
        ))}
      </Stack>
    </Box>
  )
}

export default function RiskReturnComparison({ metrics }) {
  const beforeVolatility = metrics?.fund_current_annualized_volatility
  const afterVolatility = metrics?.estimated_post_trade_annualized_volatility
  const beforeReturn = metrics?.fund_current_annualized_return
  const afterReturn = metrics?.estimated_post_trade_annualized_return

  if (!metrics || (beforeVolatility == null && afterVolatility == null
    && beforeReturn == null && afterReturn == null)) return null

  return (
    <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', md: '1fr 1fr' }, gap: 2 }}>
      <MetricDonut label="Annualized volatility" before={beforeVolatility} after={afterVolatility}
        reference={metrics.fund_strategy_band?.volatility_high} />
      <MetricDonut label="Annualized return" before={beforeReturn} after={afterReturn}
        reference={metrics.fund_strategy_band?.return_high} />
      <Typography variant="caption" color="text.secondary" sx={{ gridColumn: '1 / -1' }}>
        Historical stock returns and covariance are weighted by fund AUM; cash is treated as zero-return and zero-volatility.
      </Typography>
    </Box>
  )
}