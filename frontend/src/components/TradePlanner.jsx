import { useEffect, useState } from 'react'
import {
  Accordion, AccordionDetails, AccordionSummary, Alert, Box, Button, Checkbox, Chip, CircularProgress, Divider, Grow,
  FormControl, IconButton, InputLabel, ListItemText, MenuItem, Select, Stack, Step, StepLabel,
  Stepper, Table, TableBody, TableCell, TableHead, TableRow, TextField,
  ToggleButton, ToggleButtonGroup, Tooltip,
  Typography,
} from '@mui/material'
import CheckCircleIcon from '@mui/icons-material/CheckCircle'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import EditIcon from '@mui/icons-material/EditOutlined'
import CloseIcon from '@mui/icons-material/CloseOutlined'
import NorthEastIcon from '@mui/icons-material/NorthEast'
import { api } from '../api'
import { fmtCrValue, fmtNum, fmtPct, fmtRupee } from '../format'
import { KpiGrid, Panel, ScrollX, Stat } from './ui'
import PlanGenerationProgress from './PlanGenerationProgress'
import RiskReturnPanel from './RiskReturnPanel'
import RiskReturnComparison from './RiskReturnComparison'

const toCr = (r) => r / 1e7
const STEPS = ['PM Intent', 'Cash-Flow Planning', 'Trade Plan', 'Compliance & Risk', 'PIC Review']
const MAX_SETTLEMENT_DAYS = 33
const dateString = (date) => {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}
const dateOffset = (days) => {
  const date = new Date()
  date.setDate(date.getDate() + days)
  return dateString(date)
}
const dateOffsetFrom = (value, days) => {
  if (!value) return undefined
  const date = new Date(`${value}T00:00:00`)
  date.setDate(date.getDate() + days)
  return dateString(date)
}
const dateMonthOffset = (months) => {
  const date = new Date()
  const day = date.getDate()
  date.setDate(1)
  date.setMonth(date.getMonth() + months)
  date.setDate(Math.min(day, new Date(date.getFullYear(), date.getMonth() + 1, 0).getDate()))
  return dateString(date)
}
const daysBetween = (start, end) => Math.round(
  (Date.parse(`${end}T00:00:00Z`) - Date.parse(`${start}T00:00:00Z`)) / 86400000,
)

const ACTIONS = [
  { key: 'contribution', label: 'Contribution', needsAmount: true, needsTarget: false, hint: 'Deploy an inflow across the book toward target weights.' },
  { key: 'redemption', label: 'Redemption', needsAmount: true, needsTarget: false, hint: 'Raise cash to fund a payout by trimming over-weights.' },
  { key: 'rebalance', label: 'Rebalance', needsAmount: false, needsTarget: false, hint: 'Bring every holding back to its target weight.' },
  { key: 'increase', label: 'Increase Sector', needsAmount: true, needsTarget: true, hint: 'Add exposure to a sector.' },
  { key: 'decrease', label: 'Reduce Sector', needsAmount: true, needsTarget: true, hint: 'Trim exposure to a sector.' },
]

// Sectors the engine can buy into (match backend BUY_ALLOCATION). "Reduce"
// instead offers whatever sectors the selected fund actually holds.
const BUYABLE_SECTORS = [
  'Information Technology', 'Financial Services', 'Energy', 'FMCG', 'Automobile', 'Healthcare',
]

const PRESETS = [
  { label: 'Contribution ₹250 Cr', action: 'contribution', amount_cr: 250 },
  { label: 'Redemption ₹300 Cr', action: 'redemption', amount_cr: 300 },
  { label: 'Full Rebalance', action: 'rebalance' },
  { label: 'Increase IT ₹50 Cr', action: 'increase', targets: ['Information Technology'], amount_cr: 50 },
  { label: 'Increase IT + Healthcare ₹80 Cr', action: 'increase', targets: ['Information Technology', 'Healthcare'], amount_cr: 80 },
]

const sevOf = (s) => (s === 'FAIL' || s === 'BREACH' || s === 'HIGH' || s === 'BLOCK' ? 'error'
  : s === 'WARN' || s === 'MEDIUM' || s === 'ESCALATE' ? 'warning' : 'success')

const fmtRet = (r) => (r == null ? '—' : `${(r * 100).toFixed(2)}%`)
const formatShortDate = (value) => {
  if (!value) return '—'
  const [year, month, day] = value.split('-')
  return `${day}/${month}/${year.slice(-2)}`
}
const RISK_LABELS = {
  country: 'Portfolio exposure',
  liquidity: 'Execution liquidity',
  timing: 'Market timing',
  lock_in: 'Lock-in constraints',
  plan_creation: 'Plan validation',
  taxation: 'Tax impact',
}
const riskToneSx = (severity) => (theme) => {
  const dark = theme.palette.mode === 'dark'
  const tones = {
    HIGH: dark
      ? { color: '#F0B6B6', bgcolor: 'rgba(191, 68, 68, 0.14)', borderColor: 'rgba(240, 182, 182, 0.35)' }
      : { color: '#873C3C', bgcolor: '#F8EEEE', borderColor: '#E8C9C9' },
    MEDIUM: dark
      ? { color: '#E6CA86', bgcolor: 'rgba(194, 152, 65, 0.14)', borderColor: 'rgba(230, 202, 134, 0.32)' }
      : { color: '#755A24', bgcolor: '#F8F4E9', borderColor: '#E7D8B2' },
  }
  return tones[severity] || (dark
    ? { color: '#B9C6D2', bgcolor: 'rgba(125, 145, 165, 0.14)', borderColor: 'rgba(185, 198, 210, 0.28)' }
    : { color: '#526575', bgcolor: '#F0F4F7', borderColor: '#D7E0E8' })
}

function RiskRegister({ flags }) {
  if (!flags.length) {
    return <Typography color="text.secondary" variant="body2">No material execution risks.</Typography>
  }

  const grouped = flags.reduce((groups, flag) => {
    const category = flag.type || 'other'
    groups[category] = [...(groups[category] || []), flag]
    return groups
  }, {})
  const groups = Object.entries(grouped).sort(([a], [b]) => a.localeCompare(b))

  return (
    <Box sx={{ maxHeight: 360, overflowY: 'auto' }}>
      {groups.map(([category, items]) => {
        const highCount = items.filter((item) => item.severity === 'HIGH').length
        const reviewCount = items.filter((item) => item.severity === 'MEDIUM').length
        return (
          <Accordion key={category} disableGutters elevation={0} defaultExpanded={items.length <= 3}
            sx={{
              bgcolor: 'transparent',
              borderBottom: 1,
              borderColor: 'divider',
              '&:before': { display: 'none' },
            }}>
            <AccordionSummary expandIcon={<ExpandMoreIcon />} sx={{ px: 0, minHeight: 48,
              '& .MuiAccordionSummary-content': { my: 1 } }}>
              <Stack direction="row" alignItems="center" spacing={1} sx={{ flexWrap: 'wrap', pr: 1 }}>
                <Typography variant="body2" fontWeight={700}>
                  {RISK_LABELS[category] || category.replaceAll('_', ' ')}
                </Typography>
                <Chip size="small" variant="outlined" label={`${items.length} ${items.length === 1 ? 'risk' : 'risks'}`} />
                {highCount > 0 && <Chip size="small" variant="outlined" sx={riskToneSx('HIGH')} label={`${highCount} high`} />}
                {reviewCount > 0 && <Chip size="small" variant="outlined" sx={riskToneSx('MEDIUM')} label={`${reviewCount} review`} />}
              </Stack>
            </AccordionSummary>
            <AccordionDetails sx={{ px: 0, pt: 0, pb: 1.5 }}>
              <Stack divider={<Divider flexItem />}>
                {items.map((flag, index) => (
                  <Stack key={`${category}-${flag.ticker || 'scope'}-${index}`}
                    direction={{ xs: 'column', sm: 'row' }} spacing={0.75}
                    alignItems={{ sm: 'center' }} justifyContent="space-between"
                    sx={{ py: 1, gap: 1 }}>
                    <Box sx={{ minWidth: { sm: 130 }, flexShrink: 0 }}>
                      <Typography variant="body2" fontWeight={700}>
                        {flag.ticker || flag.entity || 'Portfolio'}
                      </Typography>
                    </Box>
                    <Typography variant="body2" color="text.secondary" sx={{ flex: 1, minWidth: 0 }}>
                      {flag.message}
                    </Typography>
                    <Chip size="small" label={flag.severity} variant="outlined" sx={riskToneSx(flag.severity)} />
                  </Stack>
                ))}
              </Stack>
            </AccordionDetails>
          </Accordion>
        )
      })}
    </Box>
  )
}

function TaxImpactPanel({ policyChecks, heldDueToTax }) {
  const taxChecks = policyChecks.filter((c) => c.code?.startsWith('TAX-'))
  if (!taxChecks.length && !heldDueToTax.length) {
    return <Typography color="text.secondary" variant="body2">No tax checks for this plan.</Typography>
  }
  return (
    <>
      {taxChecks.length > 0 && (
        <Box sx={{ maxHeight: 220, overflowY: 'auto', mb: heldDueToTax.length ? 2 : 0 }}>
          <Stack divider={<Divider flexItem />}>
            {taxChecks.map((c, i) => (
              <Stack key={i} direction={{ xs: 'column', sm: 'row' }} spacing={0.75}
                alignItems={{ sm: 'center' }} justifyContent="space-between" sx={{ py: 1, gap: 1 }}>
                <Box sx={{ minWidth: { sm: 110 }, flexShrink: 0 }}>
                  <Typography variant="body2" fontWeight={700}>{c.code}</Typography>
                  <Typography variant="caption" color="text.secondary">{c.entity}</Typography>
                </Box>
                <Typography variant="body2" color="text.secondary" sx={{ flex: 1, minWidth: 0 }}>
                  {c.message}
                </Typography>
                <Chip size="small" label={c.status} color={sevOf(c.status)} variant="outlined" />
              </Stack>
            ))}
          </Stack>
        </Box>
      )}
      {heldDueToTax.length > 0 && (
        <>
          <Typography variant="subtitle2" gutterBottom>Held Due to Tax ({heldDueToTax.length})</Typography>
          <ScrollX maxHeight={220}>
            <Table size="small" stickyHeader>
              <TableHead><TableRow>
                <TableCell>Security</TableCell><TableCell align="right">Return</TableCell>
                <TableCell align="right">Exit Cost</TableCell><TableCell>LTCG Turns</TableCell>
              </TableRow></TableHead>
              <TableBody>
                {heldDueToTax.map((h, i) => (
                  <TableRow key={i} hover>
                    <TableCell sx={{ fontWeight: 600 }}>{h.ticker}</TableCell>
                    <TableCell align="right" sx={{ color: 'error.main' }}>{fmtPct(h.expected_return_pct)}</TableCell>
                    <TableCell align="right">{fmtPct(h.exit_cost_pct)}</TableCell>
                    <TableCell sx={{ whiteSpace: 'nowrap' }}>{h.ltcg_maturity ? formatShortDate(h.ltcg_maturity) : '—'}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </ScrollX>
        </>
      )}
    </>
  )
}

function AdditionalPlanNotes({ warnings, riskFlags }) {
  const representedFindings = new Set(riskFlags.map((flag) => flag.message))
  const notes = warnings.filter((warning) => {
    const separator = warning.indexOf(': ')
    const message = separator >= 0 ? warning.slice(separator + 2) : warning
    return !representedFindings.has(message)
  })

  if (!notes.length) return null
  return (
    <Box sx={{ borderLeft: 3, borderColor: 'warning.main', pl: 1.5 }}>
      <Typography variant="caption" color="text.secondary" fontWeight={700}>
        Additional plan notes
      </Typography>
      <Stack spacing={0.5} sx={{ mt: 0.5 }}>
        {notes.map((note, index) => <Typography key={index} variant="body2">{note}</Typography>)}
      </Stack>
    </Box>
  )
}

function OrdersTable({ orders }) {
  if (!orders.length) return <Typography color="text.secondary">No orders generated.</Typography>
  const hasTax = orders.some((o) => o.tax)
  return (
    <ScrollX>
      <Table size="small" stickyHeader>
        <TableHead>
          <TableRow>
            <TableCell>Security</TableCell><TableCell>Side</TableCell>
            <TableCell sx={{ whiteSpace: 'nowrap' }}>Trade Date</TableCell>
            <TableCell align="right">Shares</TableCell><TableCell align="right">Price</TableCell>
            <TableCell align="right" sx={{ whiteSpace: 'nowrap' }}>Est. Value</TableCell>
            <TableCell align="right">Pred. 1-M Return</TableCell>
            {hasTax && <TableCell align="right">Est. Tax</TableCell>}
          </TableRow>
        </TableHead>
        <TableBody>
          {orders.map((o, i) => (
            <TableRow key={i} hover>
              <TableCell>
                <Typography variant="body2" fontWeight={600}>{o.ticker}</Typography>
                <Typography variant="caption" color="text.secondary">{o.sector}</Typography>
              </TableCell>
              <TableCell>
                <Chip size="small" label={o.side}
                  color={o.side === 'BUY' ? 'success' : 'error'} variant="outlined" />
              </TableCell>
              <TableCell sx={{ whiteSpace: 'nowrap' }}>{formatShortDate(o.trade_date)}</TableCell>
              <TableCell align="right">{fmtNum(o.shares)}</TableCell>
              <TableCell align="right">{fmtRupee(o.price, 0)}</TableCell>
              <TableCell align="right" sx={{ whiteSpace: 'nowrap' }}>{fmtCrValue(toCr(o.est_value))}</TableCell>
              <TableCell align="right" sx={{ color: o.expected_return >= 0 ? 'success.main' : 'error.main', fontWeight: 600 }}>
                {fmtRet(o.expected_return)}
              </TableCell>
              {hasTax && (
                <TableCell align="right">
                  {o.tax ? (
                    <Stack direction="row" spacing={0.5} justifyContent="flex-end" alignItems="center">
                      <Typography variant="body2"
                        sx={{ color: o.tax.total_tax < 0 ? 'success.main' : 'text.primary', fontWeight: 600 }}>
                        {fmtRupee(o.tax.total_tax, 0)}
                      </Typography>
                      {o.tax.stcg_gain !== 0 && <Chip size="small" variant="outlined" color="warning" label="STCG" />}
                      {o.tax.ltcg_gain !== 0 && <Chip size="small" variant="outlined" color="info" label="LTCG" />}
                    </Stack>
                  ) : '—'}
                </TableCell>
              )}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </ScrollX>
  )
}

// Forecast (predicted returns) — the TFT placeholder output that drives the
// convex optimizer. Order tickers are highlighted so the reviewer can see which
// predicted returns the plan acted on.
function ForecastPanel({ forecast, orderTickers }) {
  if (!forecast) return null
  return (
    <Panel title="Forecast — Predicted 1-M Returns"
      subtitle={`${forecast.model} · horizon ${forecast.horizon}${forecast.is_placeholder ? ' · placeholder (dummy returns until the TFT model is wired in)' : ''}`}>
      <ScrollX maxHeight={280}>
        <Table size="small" stickyHeader>
          <TableHead>
            <TableRow>
              <TableCell>Security</TableCell><TableCell>Sector</TableCell>
              <TableCell align="right">Pred. Return</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {forecast.rows.map((r) => {
              const inPlan = orderTickers.has(r.ticker)
              return (
                <TableRow key={r.ticker} hover selected={inPlan}>
                  <TableCell>
                    <Typography variant="body2" fontWeight={inPlan ? 700 : 500}>
                      {r.ticker}{inPlan ? ' •' : ''}
                    </Typography>
                  </TableCell>
                  <TableCell><Typography variant="caption" color="text.secondary">{r.sector}</Typography></TableCell>
                  <TableCell align="right" sx={{ color: r.expected_return_1m >= 0 ? 'success.main' : 'error.main', fontWeight: 600 }}>
                    {fmtRet(r.expected_return_1m)}
                  </TableCell>
                </TableRow>
              )
            })}
          </TableBody>
        </Table>
      </ScrollX>
    </Panel>
  )
}

export default function TradePlanner({ fundId }) {
  const [action, setAction] = useState('contribution')
  const [amount, setAmount] = useState(250)
  const [targets, setTargets] = useState(['Information Technology'])
  const [manualSelections, setManualSelections] = useState([])
  const [manualSectorSelections, setManualSectorSelections] = useState([])
  const [tradeDate, setTradeDate] = useState(() => dateOffset(0))
  const [settlementDate, setSettlementDate] = useState(() => dateOffset(2))
  const [method, setMethod] = useState('optimize')
  const [targetVolatility, setTargetVolatility] = useState(null)
  const [plan, setPlan] = useState(null)
  const [busy, setBusy] = useState(false)
  const [progressEvents, setProgressEvents] = useState([])
  const [error, setError] = useState(null)
  const [validationWarning, setValidationWarning] = useState('')
  const [decision, setDecision] = useState(null)
  const [fundSectors, setFundSectors] = useState([])
  const [universe, setUniverse] = useState([])
  const [holdings, setHoldings] = useState([])
  const today = dateOffset(0)
  const latestTradeDate = dateMonthOffset(1)
  const securityOptions = [...universe, ...holdings.filter((h) => !universe.some((u) => u.ticker === h.ticker))]

  const cfg = ACTIONS.find((a) => a.key === action)
  const manualUsesSectors = method === 'manual' && cfg.needsTarget
  const hasExplicitManualAmounts = method === 'manual' && (
    manualUsesSectors ? manualSectorSelections.length > 0 : manualSelections.length > 0
  )
  const needsTopLevelAmount = cfg.needsAmount && (
    action === 'contribution' || !hasExplicitManualAmounts
  )
  // Increase can target any buyable sector; Reduce only sectors the fund holds.
  const sectorOptions = action === 'increase'
    ? BUYABLE_SECTORS
    : (fundSectors.length ? fundSectors : BUYABLE_SECTORS)
  const visibleManualSectorSelections = manualSectorSelections.filter(
    (selection) => targets.includes(selection.sector) && sectorOptions.includes(selection.sector),
  )

  // On fund change: clear any plan and load the fund's sectors for the dropdown.
  useEffect(() => {
    setPlan(null); setDecision(null)
    setManualSelections([])
    setManualSectorSelections([])
    setTargetVolatility(null)
    api.sectorExposure(fundId)
      .then((d) => setFundSectors(d.sectors.map((s) => s.sector)))
      .catch(() => setFundSectors([]))
    api.universe().then((d) => setUniverse(d.universe)).catch(() => setUniverse([]))
    api.holdings(fundId).then((d) => setHoldings(d.holdings)).catch(() => setHoldings([]))
  }, [fundId])

  // Keep the selected sectors valid for the current action / fund.
  useEffect(() => {
    if (!cfg.needsTarget) return
    const options = method === 'manual' && !manualUsesSectors
      ? (action === 'increase' ? universe.map((u) => u.ticker) : holdings.map((h) => h.ticker))
      : sectorOptions
    const valid = targets.filter((t) => options.includes(t))
    if (valid.length === 0 && options.length) setTargets([options[0]])
    else if (valid.length !== targets.length) setTargets(valid)
  }, [action, fundSectors, method, universe, holdings, manualUsesSectors]) // eslint-disable-line react-hooks/exhaustive-deps

  function applyPreset(p) {
    setAction(p.action)
    if (p.amount_cr != null) setAmount(p.amount_cr)
    if (p.targets) setTargets(p.targets)
    setPlan(null); setDecision(null)
  }

  async function generate() {
    const horizon = daysBetween(tradeDate, settlementDate)
    if (horizon < 1 || horizon > MAX_SETTLEMENT_DAYS) {
      setValidationWarning(`Settlement date must be 1 to ${MAX_SETTLEMENT_DAYS} days after the trade date.`)
      setError(null)
      return
    }
    const manualAmounts = manualUsesSectors ? manualSectorSelections : manualSelections
    const hasNegativeManualAmount = method === 'manual'
      && manualAmounts.some((selection) => Number(selection.amount_cr) < 0)
    if ((needsTopLevelAmount && Number(amount) < 0) || hasNegativeManualAmount) {
      setValidationWarning('Amounts must be zero or greater. Correct the highlighted amount(s) before generating the plan.')
      setError(null)
      return
    }
    setValidationWarning('')
    setBusy(true); setError(null); setDecision(null); setPlan(null); setProgressEvents([])
    try {
      const payload = {
        action,
        amount_cr: needsTopLevelAmount ? Number(amount) : undefined,
        targets: cfg.needsTarget ? targets : undefined,
        manual_selections: method === 'manual' && !manualUsesSectors ? manualSelections : undefined,
        manual_sector_selections: method === 'manual' && manualUsesSectors ? manualSectorSelections : undefined,
        trade_date: tradeDate,
        settlement_date: settlementDate,
        horizon_days: horizon,
        method,
        fund_id: fundId,
        target_volatility: targetVolatility ?? undefined,
      }
      const generatedPlan = await api.createTradePlanStream(payload, {
        onProgress: (evt) => setProgressEvents((prev) => [...prev, evt]),
      })
      setPlan(generatedPlan)
    } catch (e) {
      setError(e.message)
    } finally { setBusy(false) }
  }

  function closePlan() {
    setPlan(null); setDecision(null)
  }

  async function decide(choice) {
    if (!plan) return
    try {
      setDecision(await api.decide(plan.plan_id, { decision: choice, reviewer: 'PIC Associate' }))
    } catch (e) { setError(e.message) }
  }

  const s = plan?.summary
  const activePhaseIndex = progressEvents.length ? progressEvents[progressEvents.length - 1].index : 0
  const activeStep = plan ? 4 : busy ? Math.min(4, activePhaseIndex) : 0
  const orderTickers = new Set((plan?.orders || []).map((o) => o.ticker))
  const opt = plan?.optimization

  return (
    <Stack spacing={2.5}>
      <Stepper activeStep={activeStep} alternativeLabel sx={{ display: { xs: 'none', md: 'flex' } }}>
        {STEPS.map((label) => <Step key={label}><StepLabel>{label}</StepLabel></Step>)}
      </Stepper>

      {/* Intent — the input, given a highlighted card at the top */}
      <Panel highlight title="Portfolio Manager Intent" sx={{
        pointerEvents: busy ? 'none' : 'auto',
        opacity: busy ? 0.55 : 1,
        transition: 'opacity 180ms ease',
      }}>
        <ToggleButtonGroup exclusive value={action} color="primary" size="small"
          onChange={(_, v) => v && (setAction(v), setPlan(null), setDecision(null))}
          sx={{ flexWrap: 'wrap', mb: 2 }}>
          {ACTIONS.map((a) => <ToggleButton key={a.key} value={a.key}>{a.label}</ToggleButton>)}
        </ToggleButtonGroup>

        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5} alignItems={{ sm: 'center' }} sx={{ mb: 2 }}>
          <Typography variant="body2" color="text.secondary" sx={{ fontWeight: 600 }}>Allocation method</Typography>
          <ToggleButtonGroup exclusive value={method} color="secondary" size="small"
            onChange={(_, v) => v && (setMethod(v), setPlan(null), setDecision(null))}>
            <ToggleButton value="manual">Manual</ToggleButton>
            <ToggleButton value="rules">Rules-Based</ToggleButton>
            <ToggleButton value="optimize">Convex Optimization</ToggleButton>
          </ToggleButtonGroup>
          <Typography variant="caption" color="text.secondary">
            {method === 'manual'
              ? 'Select securities or sectors and enter the amount for each one.'
              : method === 'optimize'
              ? 'Forecast-driven CVXPY optimizer picks the allocation; the same compliance & risk rules still apply.'
              : 'Heuristic drift/target rules pick the allocation.'}
          </Typography>
        </Stack>

        <Box sx={{ mb: 2 }}>
          <Typography variant="body2" color="text.secondary" sx={{ fontWeight: 600, mb: 0.5 }}>
            Risk / return target
          </Typography>
          <RiskReturnPanel fundId={fundId} targetVolatility={targetVolatility}
            onChangeTargetVolatility={(value) => {
              setTargetVolatility(value)
              setPlan(null)
              setDecision(null)
            }} afterPlan={plan?.risk_return} />
        </Box>

        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}
          alignItems={{ sm: 'flex-start' }} flexWrap="wrap">
          {method === 'manual' && !manualUsesSectors ? (
            <Stack spacing={1} sx={{ width: { xs: '100%', sm: 420 }, flexShrink: 0 }}>
              <FormControl size="small" sx={{ width: '100%' }}>
                <InputLabel id="manual-securities-label">Securities</InputLabel>
                <Select labelId="manual-securities-label" label="Securities" multiple
                value={manualSelections.map((s) => s.ticker)}
                onChange={(e) => {
                  const tickers = e.target.value
                  setManualSelections(tickers.map((ticker) => ({
                    ticker,
                    side: manualSelections.find((s) => s.ticker === ticker)?.side || 'BUY',
                    amount_cr: manualSelections.find((s) => s.ticker === ticker)?.amount_cr || 0,
                  })))
                }}
                sx={{ width: '100%', '& .MuiSelect-select': { overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } }}
                renderValue={(selected) => selected.join(', ')}
                MenuProps={{ disableAutoFocusItem: true }}>
                {securityOptions.map((security) => (
                  <MenuItem key={security.ticker} value={security.ticker}>
                    <Checkbox size="small" checked={manualSelections.some((s) => s.ticker === security.ticker)} />
                    <ListItemText primary={security.ticker} secondary={security.name} />
                  </MenuItem>
                ))}
                </Select>
                <Typography variant="caption" color="text.secondary" sx={{ mt: 0.5 }}>
                  Select securities, then choose BUY or SELL for each.
                </Typography>
              </FormControl>
              {manualSelections.map((selection) => (
                <Stack key={selection.ticker} direction="row" alignItems="center" justifyContent="space-between">
                  <Typography variant="body2" fontWeight={600}>{selection.ticker}</Typography>
                  <Stack direction="row" spacing={1} alignItems="center">
                    <TextField size="small" type="number" label="₹ Cr" value={selection.amount_cr}
                      error={Number(selection.amount_cr) < 0}
                      helperText={Number(selection.amount_cr) < 0 ? 'Cannot be negative' : ' '}
                      inputProps={{ min: 0 }}
                      onChange={(e) => {
                        setValidationWarning('')
                        setManualSelections((current) => current.map((item) =>
                          item.ticker === selection.ticker ? { ...item, amount_cr: e.target.value } : item))
                      }}
                      sx={{ width: 105 }} />
                    <ToggleButtonGroup exclusive size="small" value={selection.side}
                      onChange={(_, side) => side && setManualSelections((current) => current.map((item) =>
                        item.ticker === selection.ticker ? { ...item, side } : item))}>
                      <ToggleButton value="BUY">BUY</ToggleButton>
                      <ToggleButton value="SELL">SELL</ToggleButton>
                    </ToggleButtonGroup>
                  </Stack>
                </Stack>
              ))}
            </Stack>
          ) : cfg.needsTarget && (
            <Stack spacing={1.25} sx={{ width: { xs: '100%', sm: 520 }, maxWidth: '100%', minWidth: 0, flexShrink: 0 }}>
              <FormControl size="small" sx={{ width: '100%', minWidth: 0 }}>
                <InputLabel id="sector-targets-label">Sectors</InputLabel>
                <Select labelId="sector-targets-label" label="Sectors" multiple
                  value={targets.filter((t) => sectorOptions.includes(t))}
                  onChange={(e) => {
                    const selected = e.target.value
                    setTargets(selected)
                    setManualSectorSelections(selected.map((sector) => ({
                      sector,
                      amount_cr: manualSectorSelections.find((item) => item.sector === sector)?.amount_cr || 0,
                    })))
                  }}
                  sx={{ width: '100%', minWidth: 0,
                    '& .MuiSelect-select': { overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } }}
                  renderValue={(selected) => selected.join(', ')}
                  MenuProps={{ disableAutoFocusItem: true }}>
                  {sectorOptions.map((sector) => (
                    <MenuItem key={sector} value={sector}>
                      <Checkbox size="small" checked={targets.indexOf(sector) > -1} />
                      <ListItemText primary={sector} />
                    </MenuItem>
                  ))}
                </Select>
                <Typography variant="caption" color="text.secondary" sx={{ mt: 0.5 }}>
                  Enter a separate amount for each selected sector.
                </Typography>
              </FormControl>
              {manualUsesSectors && visibleManualSectorSelections.length > 0 && (
                <Box sx={{ display: 'grid', gridTemplateColumns: { xs: 'minmax(0, 1fr)', sm: 'repeat(2, minmax(0, 1fr))' }, gap: 1.25 }}>
                  {visibleManualSectorSelections.map((selection) => (
                    <Box key={selection.sector} sx={{ minWidth: 0 }}>
                      <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 0.5 }}>
                        {selection.sector}
                      </Typography>
                      <TextField size="small" type="number" label="Amount (₹ Cr)" value={selection.amount_cr}
                        error={Number(selection.amount_cr) < 0}
                        helperText={Number(selection.amount_cr) < 0 ? 'Cannot be negative' : ' '}
                        inputProps={{ min: 0 }}
                        onChange={(e) => {
                          setValidationWarning('')
                          setManualSectorSelections((current) => current.map((item) =>
                            item.sector === selection.sector ? { ...item, amount_cr: e.target.value } : item))
                        }}
                        sx={{ width: '100%' }} />
                    </Box>
                  ))}
                </Box>
              )}
            </Stack>
          )}
          {needsTopLevelAmount && (
            <TextField label="Amount (₹ Cr)" size="small" type="number" value={amount}
              error={Number(amount) < 0}
              helperText={Number(amount) < 0 ? 'Cannot be negative' : ' '}
              inputProps={{ min: 0 }}
              onChange={(e) => {
                setValidationWarning('')
                setAmount(e.target.value)
              }}
              sx={{ width: { xs: '100%', sm: 150 }, flexShrink: 0 }} />
          )}
          <TextField label="Trade date" type="date" size="small" value={tradeDate}
            slotProps={{ htmlInput: { min: today, max: latestTradeDate } }}
            onChange={(e) => { setTradeDate(e.target.value); setPlan(null); setDecision(null) }}
            InputLabelProps={{ shrink: true }}
            sx={{ width: { xs: '100%', sm: 170 }, flexShrink: 0 }} />
          <TextField label="Settlement date" type="date" size="small" value={settlementDate}
            slotProps={{ htmlInput: {
              min: tradeDate,
              max: dateOffsetFrom(tradeDate, MAX_SETTLEMENT_DAYS),
            } }}
            onChange={(e) => { setSettlementDate(e.target.value); setPlan(null); setDecision(null) }}
            InputLabelProps={{ shrink: true }}
            sx={{ width: { xs: '100%', sm: 190 }, flexShrink: 0 }} />
          <Button variant="contained" size="large" onClick={generate} disabled={busy}
            sx={{ width: 170, minWidth: 170, height: 40, flexShrink: 0 }}
            startIcon={busy ? <CircularProgress size={16} color="inherit" /> : null}>
            {busy ? 'Generating…' : 'Generate Plan'}
          </Button>
        </Stack>
        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1 }}>{cfg.hint}</Typography>

        <Stack direction="row" spacing={1} sx={{ mt: 2, flexWrap: 'wrap', gap: 1 }}>
          {PRESETS.map((p) => (
            <Chip key={p.label} label={p.label} size="small" variant="outlined"
              onClick={() => applyPreset(p)} clickable />
          ))}
        </Stack>
      </Panel>

      {validationWarning && <Alert severity="warning">{validationWarning}</Alert>}
      {error && <Alert severity="error">{error} — is the backend running on :8000?</Alert>}

      {busy && <PlanGenerationProgress events={progressEvents} />}

      {plan && (
        <Grow in timeout={450}>
          <Stack spacing={2.5}>
            <Stack direction="row" justifyContent="flex-end" sx={{ mb: -1.5 }}>
              <Tooltip title="Close generated plan">
                <IconButton size="small" onClick={closePlan} aria-label="Close generated plan">
                  <CloseIcon fontSize="small" />
                </IconButton>
              </Tooltip>
            </Stack>
            {/* Summary tiles — investable cash leads with an accent */}
            <KpiGrid min={190}>
              <Stat accent label="Investable Cash" value={fmtCrValue(toCr(s.investable_amount), 0)}
                sub={`${plan.intent.trade_date} to ${plan.intent.settlement_date}`} color="secondary.main" />
              <Stat label="Buy / Sell" value={`${fmtCrValue(toCr(s.total_buy_value), 0)}`}
                sub={`sell ${fmtCrValue(toCr(s.total_sell_value), 0)} · ${s.order_count} orders`} />
              <Stat label="Net Cash Impact" value={fmtCrValue(toCr(s.net_cash_impact), 0)}
                sub={`${s.net_cash_impact < 0 ? 'cash deployed' : 'cash raised'} · ${fmtCrValue(toCr(s.net_cash_after_tax), 0)} after tax`}
                color={s.net_cash_impact < 0 ? 'error.main' : 'success.main'} />
              <Stat label="Compliance" value={<Chip label={s.compliance_status} color={sevOf(s.compliance_status)} size="small" />}
                sub={decision ? decision.status : plan.status} />
              {s.total_sell_value > 0 && (
                <Stat label="Est. Exit Tax" value={fmtCrValue(toCr(s.est_total_tax), 2)}
                  sub={`${s.tax_drag_bps} bps drag · ${s.stcg_share_pct}% STCG`}
                  color={s.est_total_tax < 0 ? 'success.main' : s.tax_drag_bps > 60 ? 'error.main' : 'text.primary'} />
              )}
            </KpiGrid>

            <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap', gap: 1 }}>
              <Chip size="small" color={plan.allocation_method === 'optimize' ? 'secondary' : 'default'}
                variant={plan.allocation_method === 'optimize' ? 'filled' : 'outlined'}
                label={plan.allocation_method === 'optimize' ? 'Convex Optimization'
                  : plan.allocation_method === 'manual' ? 'Manual' : 'Rules-Based'} />
              {plan.intent?.method === 'optimize' && plan.allocation_method === 'rules' && (
                <Chip size="small" color="warning" variant="outlined" label="optimizer fell back to rules" />
              )}
            </Stack>

            <Alert severity={sevOf(s.compliance_status)} variant="outlined">{plan.recommendation}</Alert>
            {opt && (
              <Alert severity="info" variant="outlined">
                <strong>Optimizer:</strong> {opt.objective} · solver {opt.solver} ({opt.status})
                {opt.deployed_return_pct != null && <> · deployed-capital return {opt.deployed_return_pct}%</>}
                {opt.given_up_return_cr != null && <> · return given up {fmtCrValue(opt.given_up_return_cr)} to raise {fmtCrValue(opt.amount_raised_cr)}</>}
                {opt.expected_return_post_pct != null && <> · book return {opt.expected_return_pre_pct}% → {opt.expected_return_post_pct}% (turnover ≤ {opt.turnover_budget_pct}%)</>}
                {opt.est_tax_cr != null && <> · est. tax {fmtCrValue(opt.est_tax_cr)}</>}
                {opt.tax_saved_vs_naive_cr != null && opt.tax_saved_vs_naive_cr > 0 && (
                  <> · <strong>tax-aware saved {fmtCrValue(opt.tax_saved_vs_naive_cr)} vs a tax-blind plan</strong></>
                )}
                {opt.risk_target_achieved_annual != null && (
                  <> · historical volatility target {fmtPct((opt.target_volatility ?? opt.sigma_max_annual) * 100)}
                    → achieved {fmtPct(opt.risk_target_achieved_annual * 100)}</>
                )}
                {opt.initial_risk_bound_applied === false && (
                  <> · initial convex risk bound was relaxed before target fitting</>
                )}
              </Alert>
            )}
            {plan.risk_return && (
              <Alert severity={plan.risk_return.volatility_target_reached === false ? 'warning' : 'info'} variant="outlined">
                <strong>Historical risk/return:</strong> annualized volatility {fmtPct((plan.risk_return.estimated_post_trade_annualized_volatility || 0) * 100)}
                {plan.risk_return.target_volatility != null && <> vs target {fmtPct(plan.risk_return.target_volatility * 100)}</>}
                {plan.risk_return.volatility_target_gap != null && (
                  <> · target gap {fmtPct(plan.risk_return.volatility_target_gap * 100)}</>
                )}
                {plan.risk_return.estimated_post_trade_annualized_return != null && (
                  <> · historical annualized return {fmtPct(plan.risk_return.estimated_post_trade_annualized_return * 100)}</>
                )}
                {plan.risk_return.historical_metric_coverage_pct != null && (
                  <> · historical coverage {fmtPct(plan.risk_return.historical_metric_coverage_pct)}</>
                )}
                {plan.allocation_method !== 'optimize' && (
                  <> · manual/rules allocations are not retuned to the risk target</>
                )}
              </Alert>
            )}
            <AdditionalPlanNotes warnings={plan.warnings || []} riskFlags={plan.risk_flags || []} />

            {/* Bento: the generated orders are the hero (wide, highlighted);
                cash-flow + pending context ride a side rail. */}
            <Box sx={{ display: 'grid', gap: 2.5, alignItems: 'start',
              gridTemplateColumns: { xs: '1fr', lg: '1.6fr 1fr' } }}>
              <Panel highlight title={`Generated Orders (${plan.orders.length})`}>
                {plan.funding_sources.length > 0 && (
                  <Stack direction="row" spacing={1} sx={{ mb: 1.5, flexWrap: 'wrap', gap: 1 }}>
                    {plan.funding_sources.map((f, i) => (
                      <Chip key={i} size="small" variant="outlined" color="primary"
                        label={`${f.ticker}: ${fmtCrValue(toCr(f.est_value))}`} title={f.reason} />
                    ))}
                  </Stack>
                )}
                <OrdersTable orders={plan.orders} />
              </Panel>

              <Stack spacing={2.5}>
                <ForecastPanel forecast={plan.forecast} orderTickers={orderTickers} />

                <Panel title={`Cash-Flow Planning → ${fmtCrValue(toCr(plan.cash_flow_planning.investable_amount))}`}>
                  <Table size="small">
                    <TableBody>
                      {plan.cash_flow_planning.line_items.map((li, i) => (
                        <TableRow key={i}>
                          <TableCell sx={{ border: 0, py: 0.5 }}>{li.label}</TableCell>
                          <TableCell align="right" sx={{ border: 0, py: 0.5, color: li.amount < 0 ? 'error.main' : li.amount > 0 ? 'success.main' : 'text.primary' }}>
                            {fmtCrValue(toCr(li.amount))}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                  {plan.cash_flow_planning.net_cash_after_tax != null && (
                    <>
                      <Divider sx={{ my: 1 }} />
                      <Stack direction="row" alignItems="center" justifyContent="space-between">
                        <Box>
                          <Typography variant="body2" fontWeight={700}>Net cash after tax</Typography>
                          <Typography variant="caption" color="text.secondary">
                            Post-trade: buy/sell value net of est. exit tax and buy-side STT/stamp duty
                          </Typography>
                        </Box>
                        <Typography variant="body2" fontWeight={700}
                          color={plan.cash_flow_planning.net_cash_after_tax < 0 ? 'error.main' : 'success.main'}>
                          {fmtCrValue(toCr(plan.cash_flow_planning.net_cash_after_tax))}
                        </Typography>
                      </Stack>
                    </>
                  )}
                </Panel>

                <Panel title={`Pending / Unsettled (${plan.pending_trades.length})`}
                  subtitle={`Committed but unsettled (T+1 / T+2) — already reflected above. Net ${fmtCrValue(plan.pending_net_cr)}.`}>
                  {plan.pending_trades.length === 0 ? (
                    <Typography color="text.secondary" variant="body2">No pending trades.</Typography>
                  ) : (
                    <ScrollX maxHeight={240}>
                      <Table size="small" stickyHeader>
                        <TableHead>
                          <TableRow>
                            <TableCell>Security</TableCell><TableCell>Side</TableCell>
                            <TableCell align="right">Cash</TableCell><TableCell>Cycle</TableCell>
                          </TableRow>
                        </TableHead>
                        <TableBody>
                          {plan.pending_trades.map((t) => (
                            <TableRow key={t.trade_id} hover>
                              <TableCell><Typography variant="body2" fontWeight={600}>{t.ticker}</Typography></TableCell>
                              <TableCell><Chip size="small" label={t.side} color={t.side === 'BUY' ? 'success' : 'error'} variant="outlined" /></TableCell>
                              <TableCell align="right" sx={{ color: t.cash_impact_cr < 0 ? 'error.main' : 'success.main', fontWeight: 600 }}>
                                {fmtCrValue(t.cash_impact_cr)}
                              </TableCell>
                              <TableCell><Chip size="small" label={t.cycle} color={t.cycle === 'T+1' ? 'primary' : 'secondary'} /></TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    </ScrollX>
                  )}
                </Panel>
              </Stack>
            </Box>

            {/* Compliance, Tax & Risk — three-up on wide screens */}
            <Panel title="Compliance, Tax & Risk">
              <Box sx={{ display: 'grid', gap: 3, gridTemplateColumns: { xs: '1fr', md: '1fr 1fr', xl: '1.1fr 1fr 1fr' } }}>
                <Box>
                  <Typography variant="subtitle2" gutterBottom>Compliance</Typography>
                  {plan.compliance_checks.length === 0 ? <Typography color="text.secondary" variant="body2">No checks triggered.</Typography> : (
                    <ScrollX>
                      <Table size="small">
                        <TableHead><TableRow>
                          <TableCell>Rule</TableCell><TableCell>Entity</TableCell>
                          <TableCell align="right">Current → Proj</TableCell><TableCell align="right">Limit</TableCell><TableCell>Status</TableCell>
                        </TableRow></TableHead>
                        <TableBody>
                          {plan.compliance_checks.map((c, i) => (
                            <TableRow key={i} hover>
                              <TableCell>{c.rule}</TableCell>
                              <TableCell sx={{ fontWeight: 600 }}>{c.entity}</TableCell>
                              <TableCell align="right">{fmtPct(c.current)} → {fmtPct(c.projected)}</TableCell>
                              <TableCell align="right">{fmtPct(c.limit)}</TableCell>
                              <TableCell><Chip size="small" label={c.status} color={sevOf(c.status)} variant="outlined" /></TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    </ScrollX>
                  )}
                </Box>
                <Box>
                  <Typography variant="subtitle2" gutterBottom>Tax Impact</Typography>
                  <TaxImpactPanel policyChecks={plan.policy_checks || []}
                    heldDueToTax={plan.tax_summary?.held_due_to_tax || []} />
                </Box>
                <Box>
                  <Typography variant="subtitle2" gutterBottom>Execution Risk</Typography>
                  <RiskRegister flags={plan.risk_flags || []} />
                </Box>
              </Box>
            </Panel>

            {/* PIC review — highlighted human-decision gate */}
            <Panel highlight title="PIC Review"
              action={(
                <Stack direction="row" spacing={1} alignItems="center" sx={{ flexWrap: 'wrap' }}>
                  <Chip size="small" label={plan.plan_id} variant="outlined" />
                  <Chip size="small" color="primary" label={decision ? decision.status : plan.status} />
                </Stack>
              )}>
              {!decision ? (
                <Stack direction="row" spacing={1.5} sx={{ flexWrap: 'wrap', gap: 1.5 }}>
                  <Button variant="contained" color="success" startIcon={<CheckCircleIcon />} onClick={() => decide('Approve')}>Approve</Button>
                  <Button variant="outlined" color="secondary" startIcon={<EditIcon />} onClick={() => decide('Modify')}>Modify</Button>
                  <Button variant="outlined" color="error" startIcon={<CloseIcon />} onClick={() => decide('Reject')}>Reject</Button>
                  <Button variant="outlined" color="warning" startIcon={<NorthEastIcon />} onClick={() => decide('Escalate')}>Escalate</Button>
                </Stack>
              ) : (
                <Alert severity="info">Decision recorded: <strong>{decision.decision}</strong> → {decision.status}
                  <Typography variant="caption" display="block">by {decision.reviewer} · {new Date(decision.decided_at).toLocaleString()}</Typography>
                </Alert>
              )}
              <Divider sx={{ my: 1.5 }} />
              <Typography variant="caption" color="text.secondary">
                The engine recommends; a PIC associate decides. Nothing executes without human approval.
              </Typography>
            </Panel>

            {plan.risk_return && (
              <Panel title="Risk & Return: Before vs After Plan">
                <RiskReturnComparison metrics={plan.risk_return} />
              </Panel>
            )}
          </Stack>
        </Grow>
      )}
    </Stack>
  )
}
