import { useEffect, useMemo, useState } from 'react'
import { Alert, Box, Slider, Stack, Typography, useTheme } from '@mui/material'
import { api } from '../api'

const pct = (v, digits = 1) => (v == null ? '—' : `${(v * 100).toFixed(digits)}%`)
const ABSOLUTE_MAX_VOLATILITY = 1 // never let the slider go above 100% annualized vol
const axisTicks = (min, max) => Array.from({ length: 5 }, (_, i) => {
  const value = min + ((max - min) * i) / 4
  return Math.abs(value) < 1e-10 ? 0 : value
})
const axisTickDigits = (min, max) => {
  const stepPct = ((max - min) / 4) * 100
  return stepPct >= 1 ? 0 : stepPct >= 0.1 ? 1 : 2
}

function LegendSwatch({ shape, color }) {
  const common = { width: 14, height: 14, flexShrink: 0 }
  if (shape === 'circle') {
    return <Box sx={{ ...common, borderRadius: '50%', bgcolor: color, opacity: 0.6 }} />
  }
  if (shape === 'diamond') {
    return <Box sx={{ ...common, bgcolor: color, transform: 'rotate(45deg) scale(0.7)' }} />
  }
  if (shape === 'triangle') {
    return <Box sx={{ ...common, bgcolor: color, clipPath: 'polygon(50% 0, 0 100%, 100% 100%)' }} />
  }
  if (shape === 'line') {
    return <Box sx={{ width: 14, height: 0, borderTop: '2px dashed', borderColor: color, mt: '7px' }} />
  }
  // square (band)
  return <Box sx={{ ...common, bgcolor: color, opacity: 0.25, border: '1.5px solid', borderColor: color }} />
}

function Legend({ theme, showAfterPlan }) {
  const items = [
    { shape: 'square', color: theme.palette.secondary.main, label: 'Strategy mandate band' },
    { shape: 'circle', color: theme.palette.primary.main, label: 'Holdings (size ∝ weight)' },
    { shape: 'diamond', color: theme.palette.text.primary, label: 'Fund (current)' },
    ...(showAfterPlan ? [{ shape: 'triangle', color: theme.palette.secondary.main, label: 'After plan (historical)' }] : []),
    { shape: 'line', color: theme.palette.warning.main, label: 'Target volatility' },
  ]
  return (
    <Stack direction="row" spacing={2} sx={{ flexWrap: 'wrap', rowGap: 0.5 }}>
      {items.map((it) => (
        <Stack key={it.label} direction="row" spacing={0.75} alignItems="center">
          <LegendSwatch shape={it.shape} color={it.color} />
          <Typography variant="caption" color="text.secondary">{it.label}</Typography>
        </Stack>
      ))}
    </Stack>
  )
}

// Risk/return scatter (stock-level holdings + the fund's own synthetic point)
// with the curated strategy mandate band shaded behind them, and a slider that
// sets `target_volatility` — the convex optimizer's sigma_max — defaulting to
// the band's upper edge but freely adjustable past it (capped at 100%).
// See docs/nav-risk-return-metrics.md and docs/data-v2-real-vs-curated.md.
export default function RiskReturnPanel({ fundId, targetVolatility, onChangeTargetVolatility, afterPlan }) {
  const theme = useTheme()
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [hover, setHover] = useState(null)

  useEffect(() => {
    setData(null); setError(null); setHover(null)
    api.riskReturn(fundId).then(setData).catch((e) => setError(e.message))
  }, [fundId])

  const fund = data?.fund
  const stocks = data?.stocks || []
  const afterReturn = afterPlan?.estimated_post_trade_annualized_return
  const afterVolatility = afterPlan?.estimated_post_trade_annualized_volatility
  const currentReturn = afterPlan?.fund_current_annualized_return
    ?? data?.historical_portfolio?.annualized_return
  const currentVolatility = afterPlan?.fund_current_annualized_volatility
    ?? data?.historical_portfolio?.annualized_volatility

  // Initialize the slider to the fund's curated upper band once data lands.
  useEffect(() => {
    if (fund?.strategy_volatility_high != null && targetVolatility == null) {
      onChangeTargetVolatility(fund.strategy_volatility_high)
    }
  }, [fund, targetVolatility, onChangeTargetVolatility])

  const chart = useMemo(() => {
    if (!fund) return null
    const band = {
      volLow: fund.strategy_volatility_low, volHigh: fund.strategy_volatility_high,
      retLow: fund.strategy_return_low, retHigh: fund.strategy_return_high,
    }
    const vols = [
      ...stocks.map((s) => s.annualized_volatility).filter((v) => v != null),
      currentVolatility, band.volHigh, targetVolatility, afterVolatility,
    ].filter((v) => v != null)
    const rets = [
      ...stocks.map((s) => s.annualized_return).filter((v) => v != null),
      currentReturn, band.retLow, band.retHigh, afterReturn,
    ].filter((v) => v != null)
    const xMax = Math.max(...vols, 0.05) * 1.15
    const yMin = Math.min(...rets, 0) * 1.15
    const yMax = Math.max(...rets, 0) * 1.15

    const width = 560, height = 260, left = 64, right = 16, top = 14, bottom = 44
    const plotW = width - left - right, plotH = height - top - bottom
    const xScale = (v) => left + (v / xMax) * plotW
    const yScale = (r) => top + plotH - ((r - yMin) / (yMax - yMin)) * plotH
    const xTicks = axisTicks(0, xMax)
    const yTicks = axisTicks(yMin, yMax)

    return {
      band, width, height, left, right, top, bottom, plotW, plotH,
      xScale, yScale, xMax, yMin, yMax, xTicks, yTicks,
      xTickDigits: axisTickDigits(0, xMax), yTickDigits: axisTickDigits(yMin, yMax),
    }
  }, [fund, stocks, targetVolatility, currentVolatility, currentReturn, afterVolatility, afterReturn])

  if (error) return <Alert severity="warning" variant="outlined">Risk/return data unavailable: {error}</Alert>
  if (!data || !chart) return <Typography variant="body2" color="text.secondary">Loading risk/return profile…</Typography>
  if (!fund) return <Typography variant="body2" color="text.secondary">No risk/return metrics for this fund yet.</Typography>

  const {
    band, width, height, left, top, plotW, plotH, xScale, yScale, xMax, yMin, yMax,
    xTicks, yTicks, xTickDigits, yTickDigits,
  } = chart
  const sliderMax = Math.min(Math.max(xMax, (band.volHigh || 0) * 1.5, 0.05), ABSOLUTE_MAX_VOLATILITY)
  const sliderValue = Math.min(targetVolatility ?? band.volHigh ?? 0, sliderMax)
  const hasBand = band.volLow != null && band.volHigh != null
  const outOfRange = hasBand && targetVolatility != null
    && (targetVolatility < band.volLow || targetVolatility > band.volHigh)
  const bandLeftPct = hasBand ? (band.volLow / sliderMax) * 100 : 0
  const bandWidthPct = hasBand ? ((band.volHigh - band.volLow) / sliderMax) * 100 : 0

  return (
    <Stack spacing={1}>
      <Box>
        <Typography variant="subtitle2" fontWeight={700}>{fund.fund_name}</Typography>
        <Typography variant="caption" color="text.secondary">
          {fund.category} strategy{fund.risk_grade ? ` · risk grade ${fund.risk_grade}` : ''}
        </Typography>
      </Box>

      <Legend theme={theme} showAfterPlan={afterVolatility != null && afterReturn != null} />

      <Box sx={{ overflowX: 'auto' }}>
        <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="img"
          aria-label="Stock-level and fund risk/return scatter, with the strategy mandate band">
          {/* axes */}
          <line x1={left} y1={top} x2={left} y2={top + plotH} stroke={theme.palette.divider} />
          <line x1={left} y1={top + plotH} x2={left + plotW} y2={top + plotH} stroke={theme.palette.divider} />
          {xTicks.map((tick) => (
            <g key={`x-${tick}`}>
              <line x1={xScale(tick)} y1={top} x2={xScale(tick)} y2={top + plotH}
                stroke={theme.palette.divider} strokeOpacity={0.45} />
              <line x1={xScale(tick)} y1={top + plotH} x2={xScale(tick)} y2={top + plotH + 4}
                stroke={theme.palette.text.secondary} />
              <text x={xScale(tick)} y={top + plotH + 15} textAnchor="middle" fontSize="9"
                fill={theme.palette.text.secondary}>{pct(tick, xTickDigits)}</text>
            </g>
          ))}
          {yTicks.map((tick) => (
            <g key={`y-${tick}`}>
              <line x1={left} y1={yScale(tick)} x2={left + plotW} y2={yScale(tick)}
                stroke={theme.palette.divider} strokeOpacity={0.45} />
              <line x1={left - 4} y1={yScale(tick)} x2={left} y2={yScale(tick)}
                stroke={theme.palette.text.secondary} />
              <text x={left - 8} y={yScale(tick) + 3} textAnchor="end" fontSize="9"
                fill={theme.palette.text.secondary}>{pct(tick, yTickDigits)}</text>
            </g>
          ))}
          <text x={left + plotW / 2} y={height - 4} textAnchor="middle" fontSize="10"
            fill={theme.palette.text.secondary}>Annualized volatility →</text>
          <text x={12} y={top + plotH / 2} textAnchor="middle" fontSize="10" fill={theme.palette.text.secondary}
            transform={`rotate(-90 12 ${top + plotH / 2})`}>Annualized return →</text>

          {/* curated strategy mandate band */}
          {band.volLow != null && band.volHigh != null && band.retLow != null && band.retHigh != null && (
            <rect x={xScale(band.volLow)} y={yScale(band.retHigh)}
              width={Math.max(xScale(band.volHigh) - xScale(band.volLow), 1)}
              height={Math.max(yScale(band.retLow) - yScale(band.retHigh), 1)}
              fill={theme.palette.secondary.main} opacity={0.28}
              stroke={theme.palette.secondary.main} strokeOpacity={0.9} strokeWidth={1.5} />
          )}

          {/* zero-return reference line, if in range */}
          {yMin < 0 && yMax > 0 && (
            <line x1={left} y1={yScale(0)} x2={left + plotW} y2={yScale(0)}
              stroke={theme.palette.divider} strokeDasharray="2 2" />
          )}

          {/* target volatility (slider) ceiling */}
          {targetVolatility != null && (
            <line x1={xScale(targetVolatility)} y1={top} x2={xScale(targetVolatility)} y2={top + plotH}
              stroke={theme.palette.warning.main} strokeWidth={1.5} strokeDasharray="5 3" />
          )}

          {/* holdings */}
          {stocks.filter((s) => s.annualized_volatility != null && s.annualized_return != null).map((s) => {
            const cx = xScale(s.annualized_volatility), cy = yScale(s.annualized_return)
            return (
              <circle key={s.ticker} cx={cx} cy={cy}
                r={Math.min(3 + (s.weight || 0) * 0.6, 9)}
                fill={theme.palette.primary.main}
                opacity={hover && hover.ticker !== s.ticker ? 0.3 : 0.6}
                style={{ cursor: 'default', transition: 'opacity .15s ease' }}
                onMouseEnter={() => setHover({ ...s, cx, cy })}
                onMouseLeave={() => setHover(null)}>
                <title>{`${s.ticker} · ${s.name || ''} · return ${pct(s.annualized_return)} · vol ${pct(s.annualized_volatility)} · weight ${(s.weight || 0).toFixed(1)}%`}</title>
              </circle>
            )
          })}

          {/* fund's own synthetic point */}
          {currentVolatility != null && currentReturn != null && (
            <g transform={`translate(${xScale(currentVolatility)}, ${yScale(currentReturn)})`}>
              <path d="M0 -7 L7 0 L0 7 L-7 0 Z" fill={theme.palette.text.primary} stroke={theme.palette.background.paper} strokeWidth={1.5} />
              <title>{`${fund.fund_name} (current) · return ${pct(currentReturn)} · vol ${pct(currentVolatility)}`}</title>
            </g>
          )}

          {afterVolatility != null && afterReturn != null && (
            <g transform={`translate(${xScale(afterVolatility)}, ${yScale(afterReturn)})`}>
              <path d="M0 -8 L8 7 L-8 7 Z" fill={theme.palette.secondary.main}
                stroke={theme.palette.background.paper} strokeWidth={1.5} />
              <title>{`After plan (historical) · return ${pct(afterReturn)} · vol ${pct(afterVolatility)}`}</title>
            </g>
          )}

          {/* hover label — always-visible ticker + value callout for the hovered dot */}
          {hover && (() => {
            const boxW = 168, boxH = 42
            const flip = hover.cx + 10 + boxW > width
            const bx = flip ? hover.cx - 10 - boxW : hover.cx + 10
            const by = Math.max(hover.cy - boxH - 6, 2)
            return (
              <g style={{ pointerEvents: 'none' }}>
                <rect x={bx} y={by} width={boxW} height={boxH} rx={5}
                  fill={theme.palette.background.paper} stroke={theme.palette.divider} />
                <text x={bx + 8} y={by + 16} fontSize="11" fontWeight="700" fill={theme.palette.text.primary}>
                  {hover.ticker}{hover.name ? ` · ${hover.name}` : ''}
                </text>
                <text x={bx + 8} y={by + 31} fontSize="10" fill={theme.palette.text.secondary}>
                  {`return ${pct(hover.annualized_return)} · vol ${pct(hover.annualized_volatility)} · wt ${(hover.weight || 0).toFixed(1)}%`}
                </text>
              </g>
            )
          })()}
        </svg>
      </Box>

      <Box sx={{ px: 1 }}>
        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 0.75 }}>
          Target annualized volatility for convex optimization — current book {pct(currentVolatility)}
        </Typography>
        <Box sx={{ position: 'relative', px: '6px' }}>
          {hasBand && (
            <Box sx={{
              position: 'absolute', left: `${bandLeftPct}%`, width: `${bandWidthPct}%`,
              top: '50%', transform: 'translateY(-50%)', height: 6, borderRadius: 1,
              bgcolor: 'secondary.main', opacity: 0.35, pointerEvents: 'none',
            }} />
          )}
          <Slider size="small" value={sliderValue}
            min={0} max={sliderMax} step={0.005}
            valueLabelDisplay="auto" valueLabelFormat={(v) => pct(v)}
            marks={[
              ...(band.volLow != null ? [{ value: band.volLow, label: 'Min' }] : []),
              ...(band.volHigh != null ? [{ value: band.volHigh, label: 'Max' }] : []),
            ]}
            sx={{ '& .MuiSlider-rail': { opacity: 0.25 } }}
            onChange={(_, v) => onChangeTargetVolatility(v)} />
        </Box>
        {outOfRange && (
          <Alert severity="warning" variant="outlined" sx={{ mt: 1, py: 0 }}>
            Target volatility {pct(targetVolatility)} is outside the fund's strategy mandate range
            ({pct(band.volLow)}–{pct(band.volHigh)}). The optimizer will still try to honor it, but it
            no longer matches the fund's curated mandate.
          </Alert>
        )}
      </Box>
    </Stack>
  )
}
