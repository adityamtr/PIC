import { Box, Stack, Tooltip, Typography, useTheme } from '@mui/material'
import { fmtPct } from '../format'

function MetricBars({ label, before, after, reference }) {
  const theme = useTheme()
  const series = [
    { name: 'Before', value: before, color: theme.palette.primary.main },
    { name: 'After', value: after, color: theme.palette.secondary.main },
  ]
  const values = [...series.map(({ value }) => value), reference].filter((value) => value != null)
  const min = Math.min(0, ...values)
  const max = Math.max(0, ...values)
  const range = Math.max(max - min, 0.01)
  const zero = ((0 - min) / range) * 100
  const position = (value) => ((value - min) / range) * 100
  const referencePosition = reference == null ? null : position(reference)

  return (
    <Stack spacing={1} sx={{ minWidth: 0 }}>
      <Typography variant="subtitle2" fontWeight={700}>{label}</Typography>
      <Stack spacing={1}>
        {series.map((item) => {
          const start = item.value == null ? zero : Math.min(zero, position(item.value))
          const end = item.value == null ? zero : Math.max(zero, position(item.value))
          return (
            <Box key={item.name} sx={{ display: 'grid', gridTemplateColumns: '48px minmax(0, 1fr) 58px', gap: 1, alignItems: 'center' }}>
              <Typography variant="caption" color="text.secondary">{item.name}</Typography>
              <Tooltip title={`${label} · ${item.name}: ${item.value == null ? 'unavailable' : fmtPct(item.value * 100, 2)}`}>
                <Box tabIndex={0} role="img"
                  aria-label={`${label}, ${item.name}: ${item.value == null ? 'unavailable' : fmtPct(item.value * 100, 2)}`}
                  sx={{ position: 'relative', height: 16, cursor: 'default', '&:hover .metric-bar, &:focus-visible .metric-bar': { opacity: 1, filter: 'brightness(1.12)' } }}>
                  <Box sx={{ position: 'absolute', inset: '6px 0', bgcolor: 'action.hover', borderRadius: 1 }} />
                  <Box sx={{ position: 'absolute', top: 3, bottom: 3, left: `${zero}%`, width: '1px', bgcolor: 'text.disabled' }} />
                  {referencePosition != null && (
                    <Box sx={{ position: 'absolute', top: 1, bottom: 1, left: `${referencePosition}%`, borderLeft: '1px dashed', borderColor: 'text.secondary' }} />
                  )}
                  {item.value != null && (
                    <Box className="metric-bar" sx={{ position: 'absolute', top: 3, bottom: 3,
                      left: `${start}%`, width: `${Math.max(end - start, 0.7)}%`, minWidth: 2,
                      bgcolor: item.color, borderRadius: 0.5, opacity: 0.84,
                      transition: 'opacity 120ms ease, filter 120ms ease' }} />
                  )}
                </Box>
              </Tooltip>
              <Typography variant="caption" fontWeight={600} textAlign="right"
                sx={{ fontVariantNumeric: 'tabular-nums', whiteSpace: 'nowrap' }}>
                {item.value == null ? '—' : fmtPct(item.value * 100, 2)}
              </Typography>
            </Box>
          )
        })}
      </Stack>
      <Stack direction="row" justifyContent="space-between" sx={{ pl: '56px', pr: '66px' }}>
        <Typography variant="caption" color="text.disabled">{fmtPct(min * 100, 1)}</Typography>
        {reference != null && (
          <Typography variant="caption" color="text.secondary">Strategy limit {fmtPct(reference * 100, 2)}</Typography>
        )}
        <Typography variant="caption" color="text.disabled">{fmtPct(max * 100, 1)}</Typography>
      </Stack>
    </Stack>
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
      <MetricBars label="Annualized volatility" before={beforeVolatility} after={afterVolatility}
        reference={metrics.fund_strategy_band?.volatility_high} />
      <MetricBars label="Annualized return" before={beforeReturn} after={afterReturn}
        reference={metrics.fund_strategy_band?.return_high} />
      <Typography variant="caption" color="text.secondary" sx={{ gridColumn: '1 / -1' }}>
        Historical stock returns and covariance are weighted by fund AUM; cash is treated as zero-return and zero-volatility.
      </Typography>
    </Box>
  )
}