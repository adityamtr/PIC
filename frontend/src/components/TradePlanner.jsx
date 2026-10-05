import { useEffect, useState } from 'react'
import {
  Accordion, AccordionDetails, AccordionSummary, Alert, Box, Button, Checkbox, Chip, CircularProgress, Divider, Grow,
  FormControl, IconButton, InputLabel, ListItemText, MenuItem, Select, Stack, Step, StepLabel,
  Stepper, Table, TableBody, TableCell, TableHead, TableRow, TextField,
  ToggleButton, ToggleButtonGroup, Tooltip,
  Typography,
} from '@mui/material'
import CheckCircleIcon from '@mui/icons-material/CheckCircle'
import EmailOutlinedIcon from '@mui/icons-material/EmailOutlined'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import CloseIcon from '@mui/icons-material/CloseOutlined'
import NorthEastIcon from '@mui/icons-material/NorthEast'
import QueryStatsOutlinedIcon from '@mui/icons-material/QueryStatsOutlined'
import AssignmentOutlinedIcon from '@mui/icons-material/AssignmentOutlined'
import AccountBalanceWalletOutlinedIcon from '@mui/icons-material/AccountBalanceWalletOutlined'
import SwapVertOutlinedIcon from '@mui/icons-material/SwapVertOutlined'
import AccountBalanceOutlinedIcon from '@mui/icons-material/AccountBalanceOutlined'
import GppGoodOutlinedIcon from '@mui/icons-material/GppGoodOutlined'
import ReceiptLongOutlinedIcon from '@mui/icons-material/ReceiptLongOutlined'
import ScheduleOutlinedIcon from '@mui/icons-material/ScheduleOutlined'
import FactCheckOutlinedIcon from '@mui/icons-material/FactCheckOutlined'
import ShowChartOutlinedIcon from '@mui/icons-material/ShowChartOutlined'
import AddCircleOutlineIcon from '@mui/icons-material/AddCircleOutlined'
import RemoveCircleOutlineIcon from '@mui/icons-material/RemoveCircleOutlined'
import AutorenewIcon from '@mui/icons-material/Autorenew'
import TrendingUpOutlinedIcon from '@mui/icons-material/TrendingUpOutlined'
import TrendingDownOutlinedIcon from '@mui/icons-material/TrendingDownOutlined'
import EditNoteOutlinedIcon from '@mui/icons-material/EditNoteOutlined'
import RuleOutlinedIcon from '@mui/icons-material/RuleOutlined'
import FunctionsOutlinedIcon from '@mui/icons-material/FunctionsOutlined'
import PlayArrowOutlinedIcon from '@mui/icons-material/PlayArrowOutlined'
import { api } from '../api'
import { fmtCrValue, fmtNum, fmtPct, fmtRupee } from '../format'
import { KpiGrid, Panel, ScrollX, Stat } from './ui'
import PlanGenerationProgress, { GenerationStepsSummary } from './PlanGenerationProgress'
import RiskReturnPanel from './RiskReturnPanel'
import RiskReturnComparison from './RiskReturnComparison'
import PlannerAssistant from './PlannerAssistant'

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
const assistantFieldSx = (active) => active ? ({
  animation: 'assistant-field-change 700ms ease-out',
  '@keyframes assistant-field-change': {
    '0%': { boxShadow: '0 0 0 0 rgba(20, 126, 119, 0.45)' },
    '100%': { boxShadow: '0 0 0 8px rgba(20, 126, 119, 0)' },
  },
}) : {}

const ACTIONS = [
  { key: 'contribution', label: 'Contribution', icon: AddCircleOutlineIcon, needsAmount: true, needsTarget: false, hint: 'Deploy an inflow across the book toward target weights.' },
  { key: 'redemption', label: 'Redemption', icon: RemoveCircleOutlineIcon, needsAmount: true, needsTarget: false, hint: 'Raise cash to fund a payout by trimming over-weights.' },
  { key: 'rebalance', label: 'Rebalance', icon: AutorenewIcon, needsAmount: false, needsTarget: false, hint: 'Bring every holding back to its target weight.' },
  { key: 'increase', label: 'Increase Sector', icon: TrendingUpOutlinedIcon, needsAmount: true, needsTarget: true, hint: 'Add exposure to a sector.' },
  { key: 'decrease', label: 'Reduce Sector', icon: TrendingDownOutlinedIcon, needsAmount: true, needsTarget: true, hint: 'Trim exposure to a sector.' },
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

const sevOf = (s) => (s === 'FAIL' || s === 'BREACH' || s === 'HIGH' || s === 'BLOCK' || s === 'BLOCKED' ? 'error'
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
const riskDecisionLabel = (flag) => ({
  BLOCK: 'BLOCKED',
  ESCALATE: 'ACTION',
  WARN: 'REVIEW',
}[flag.status] || (flag.severity === 'MEDIUM' ? 'REVIEW' : flag.severity))

const riskDecisionTone = (flag) => (
  flag.status === 'BLOCK' || flag.severity === 'HIGH' ? 'HIGH'
    : flag.status === 'ESCALATE' ? 'MEDIUM'
      : flag.status === 'WARN' || flag.severity === 'MEDIUM' ? 'REVIEW' : flag.severity
)

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
        const actionCount = items.filter((item) => item.status === 'ESCALATE').length
        const reviewCount = items.filter((item) => item.status === 'WARN'
          || (!item.status && item.severity === 'MEDIUM')).length
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
                    <Chip size="small" label={riskDecisionLabel(flag)} variant="outlined"
                      sx={riskToneSx(riskDecisionTone(flag))} />
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
    <Panel icon={<QueryStatsOutlinedIcon />} title="Forecast — Predicted 1-M Returns"
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

export default function TradePlanner({ fundId, funds, onChangeFundId, onContinueToEmail }) {
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
  const [assistantHighlight, setAssistantHighlight] = useState('')
  const today = dateOffset(0)
  const latestTradeDate = dateMonthOffset(1)
  const securityOptions = [...universe, ...holdings.filter((h) => !universe.some((u) => u.ticker === h.ticker))]

  const cfg = ACTIONS.find((a) => a.key === action)
  const manualUsesSectors = method === 'manual' && cfg.needsTarget
  // Contribution only deploys cash (BUY); redemption only raises it (SELL).
  // Rebalance can go either way, so it keeps the BUY/SELL choice.
  const forcedSide = action === 'contribution' ? 'BUY' : action === 'redemption' ? 'SELL' : null
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

  // Contribution/redemption lock manual security picks to BUY/SELL respectively —
  // flip any picks made before the action changed so they stay consistent.
  useEffect(() => {
    if (!forcedSide) return
    setManualSelections((current) => {
      if (current.every((item) => item.side === forcedSide)) return current
      return current.map((item) => ({ ...item, side: forcedSide }))
    })
  }, [forcedSide])

  function applyPreset(p) {
    setAction(p.action)
    if (p.amount_cr != null) setAmount(p.amount_cr)
    if (p.targets) setTargets(p.targets)
    setPlan(null); setDecision(null)
  }

  async function applyAssistantUpdates(updates) {
    const order = ['fund_id', 'action', 'method', 'amount_cr', 'manual_selections',
      'manual_sector_selections', 'targets', 'trade_date', 'horizon_days', 'settlement_date',
      'target_volatility']
    setPlan(null)
    setDecision(null)
    setValidationWarning('')
    for (const field of order) {
      if (!(field in updates)) continue
      setAssistantHighlight(field)
      const value = updates[field]
      if (field === 'fund_id') onChangeFundId?.(value)
      if (field === 'action') setAction(value)
      if (field === 'method') setMethod(value)
      if (field === 'amount_cr') setAmount(value)
      if (field === 'manual_selections') setManualSelections(value)
      if (field === 'manual_sector_selections') setManualSectorSelections(value)
      if (field === 'targets') setTargets(value)
      if (field === 'trade_date') {
        setTradeDate(value)
        if (!('settlement_date' in updates) && !('horizon_days' in updates)) {
          const currentHorizon = Math.min(MAX_SETTLEMENT_DAYS, Math.max(1, daysBetween(tradeDate, settlementDate)))
          setSettlementDate(dateOffsetFrom(value, currentHorizon))
        }
      }
      if (field === 'horizon_days') {
        const startDate = updates.trade_date || tradeDate
        setSettlementDate(dateOffsetFrom(startDate, value))
      }
      if (field === 'settlement_date') setSettlementDate(value)
      if (field === 'target_volatility') setTargetVolatility(value)
      await new Promise((resolve) => window.setTimeout(resolve, 230))
    }
    window.setTimeout(() => setAssistantHighlight(''), 900)
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
  const planGateStatus = s?.plan_gate_status
    ?? (!plan?.execution_allowed
      ? (plan?.policy_status === 'ESCALATE' ? 'ESCALATE' : 'BLOCKED')
      : s?.compliance_status)
  const policyBlocks = (plan?.policy_checks || []).filter((check) => check.status === 'BLOCK')
  const blockedEntities = new Set(policyBlocks.map((check) => check.entity))
  const blockReasons = [
    ...policyBlocks.map((check) => ({
      key: `policy-${check.code}-${check.entity}`,
      label: `${check.code}${check.entity ? ` · ${check.entity}` : ''}`,
      message: check.message,
    })),
    ...(plan?.compliance_checks || [])
      .filter((check) => check.status === 'FAIL' && !blockedEntities.has(check.entity))
      .map((check) => ({
        key: `compliance-${check.code}-${check.entity}`,
        label: `${check.rule}${check.entity ? ` · ${check.entity}` : ''}`,
        message: check.message,
      })),
  ]
  const activePhaseIndex = progressEvents.length ? progressEvents[progressEvents.length - 1].index : 0
  // MUI Stepper marks steps with index < activeStep as complete, so once the
  // plan is ready every stage (including "PIC Review") should tick, not just
  // the first four — hence STEPS.length rather than the last index (4).
  const activeStep = plan ? STEPS.length : busy ? Math.min(4, activePhaseIndex) : 0
  const orderTickers = new Set((plan?.orders || []).map((o) => o.ticker))
  const opt = plan?.optimization

  const selectedFund = funds.find((fund) => fund.fund_id === fundId)
  const assistantDraft = {
    action,
    amount_cr: Number(amount),
    targets,
    method,
    fund_id: fundId,
    fund_name: selectedFund?.name || fundId,
    horizon_days: daysBetween(tradeDate, settlementDate),
    trade_date: tradeDate,
    settlement_date: settlementDate,
    target_volatility: targetVolatility,
    manual_selections: manualSelections,
    manual_sector_selections: manualSectorSelections,
  }

  return (
    <Box sx={{ display: 'grid', gap: 2.5, alignItems: 'start', minWidth: 0,
      gridTemplateColumns: { xs: 'minmax(0, 1fr)', lg: 'minmax(0, 1fr) minmax(320px, 360px)' },
      gridTemplateAreas: { xs: '"assistant" "planner"', lg: '"planner assistant"' } }}>
      <PlannerAssistant fundId={fundId} funds={funds} draft={assistantDraft}
        sectors={[...new Set([...BUYABLE_SECTORS, ...fundSectors])]} securities={securityOptions.map((item) => item.ticker)}
        plan={plan} onApplyUpdates={applyAssistantUpdates} onGeneratePlan={generate} busy={busy} />
      <Stack spacing={2.5} sx={{ gridArea: 'planner', minWidth: 0 }}>
      <Stepper activeStep={activeStep} alternativeLabel sx={{ display: { xs: 'none', md: 'flex' } }}>
        {STEPS.map((label) => <Step key={label}><StepLabel>{label}</StepLabel></Step>)}
      </Stepper>

      {/* Intent — the input, given a highlighted card at the top */}
      <Panel highlight icon={<AssignmentOutlinedIcon />} title="Portfolio Manager Intent" sx={{
        pointerEvents: busy ? 'none' : 'auto',
        opacity: busy ? 0.55 : 1,
        transition: 'opacity 180ms ease',
      }}>
        <ToggleButtonGroup exclusive value={action} color="primary" size="small"
          onChange={(_, v) => v && (setAction(v), setPlan(null), setDecision(null))}
          sx={{ flexWrap: 'wrap', mb: 2, ...assistantFieldSx(assistantHighlight === 'action') }}>
          {ACTIONS.map((a) => {
            const Icon = a.icon
            return (
              <ToggleButton key={a.key} value={a.key} sx={{ gap: 0.75 }}>
                <Icon fontSize="small" />{a.label}
              </ToggleButton>
            )
          })}
        </ToggleButtonGroup>

        <Stack spacing={1} sx={{ mb: 2, minWidth: 0 }}>
          <Typography variant="body2" color="text.secondary" sx={{ fontWeight: 600 }}>Allocation method</Typography>
          <ToggleButtonGroup exclusive value={method} color="secondary" size="small"
            onChange={(_, v) => v && (setMethod(v), setPlan(null), setDecision(null))}
            sx={{ width: '100%', flexWrap: 'wrap',
              '& .MuiToggleButton-root': { flex: '1 1 140px', minWidth: 0, whiteSpace: 'normal' },
              ...assistantFieldSx(assistantHighlight === 'method') }}>
            <ToggleButton value="manual" sx={{ gap: 0.75 }}>
              <EditNoteOutlinedIcon fontSize="small" />Manual
            </ToggleButton>
            <ToggleButton value="rules" sx={{ gap: 0.75 }}>
              <RuleOutlinedIcon fontSize="small" />Rules-Based
            </ToggleButton>
            <ToggleButton value="optimize" sx={{ gap: 0.75 }}>
              <FunctionsOutlinedIcon fontSize="small" />Convex Optimization
            </ToggleButton>
          </ToggleButtonGroup>
          <Typography variant="caption" color="text.secondary">
            {method === 'manual'
              ? 'Select securities or sectors and enter the amount for each one.'
              : method === 'optimize'
              ? 'Forecast-driven CVXPY optimizer picks the allocation; the same compliance & risk rules still apply.'
              : 'Heuristic drift/target rules pick the allocation.'}
          </Typography>
        </Stack>

        <Box sx={{ mb: 2, ...assistantFieldSx(assistantHighlight === 'target_volatility') }}>
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

        <Box sx={{ display: 'grid', minWidth: 0, gap: 1.5, alignItems: 'start',
          gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 220px), 1fr))',
          '& > *': { width: '100%', minWidth: 0 } }}>
          {method === 'manual' && !manualUsesSectors ? (
            <Stack spacing={1} sx={{ gridColumn: '1 / -1' }}>
              <FormControl size="small" sx={{ width: '100%' }}>
                <InputLabel id="manual-securities-label">Securities</InputLabel>
                <Select labelId="manual-securities-label" label="Securities" multiple
                value={manualSelections.map((s) => s.ticker)}
                onChange={(e) => {
                  const tickers = e.target.value
                  setManualSelections(tickers.map((ticker) => ({
                    ticker,
                    side: manualSelections.find((s) => s.ticker === ticker)?.side || forcedSide || 'BUY',
                    amount_cr: manualSelections.find((s) => s.ticker === ticker)?.amount_cr || 0,
                  })))
                }}
                sx={{ width: '100%', ...assistantFieldSx(assistantHighlight === 'manual_selections'),
                  '& .MuiSelect-select': { overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } }}
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
                  {forcedSide
                    ? `Select securities and enter an amount — every pick is a ${forcedSide === 'BUY' ? 'buy' : 'sell'} for ${cfg.label.toLowerCase()}.`
                    : 'Select securities, then choose BUY or SELL for each.'}
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
                    {forcedSide ? (
                      <Chip size="small" label={forcedSide}
                        color={forcedSide === 'BUY' ? 'success' : 'error'} variant="outlined" />
                    ) : (
                      <ToggleButtonGroup exclusive size="small" value={selection.side}
                        onChange={(_, side) => side && setManualSelections((current) => current.map((item) =>
                          item.ticker === selection.ticker ? { ...item, side } : item))}>
                        <ToggleButton value="BUY">BUY</ToggleButton>
                        <ToggleButton value="SELL">SELL</ToggleButton>
                      </ToggleButtonGroup>
                    )}
                  </Stack>
                </Stack>
              ))}
            </Stack>
          ) : cfg.needsTarget && (
            <Stack spacing={1.25} sx={{ gridColumn: '1 / -1' }}>
              <FormControl size="small" sx={{ width: '100%', minWidth: 0,
                ...assistantFieldSx(assistantHighlight === 'targets' || assistantHighlight === 'manual_sector_selections') }}>
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
                  sx={{ width: '100%', minWidth: 0, ...assistantFieldSx(assistantHighlight === 'targets'),
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
                  sx={{ ...assistantFieldSx(assistantHighlight === 'amount_cr') }} />
          )}
          <TextField label="Trade date" type="date" size="small" value={tradeDate}
            slotProps={{ htmlInput: { min: today, max: latestTradeDate } }}
            onChange={(e) => { setTradeDate(e.target.value); setPlan(null); setDecision(null) }}
            InputLabelProps={{ shrink: true }}
            sx={{ ...assistantFieldSx(assistantHighlight === 'trade_date') }} />
          <TextField label="Settlement date" type="date" size="small" value={settlementDate}
            slotProps={{ htmlInput: {
              min: tradeDate,
              max: dateOffsetFrom(tradeDate, MAX_SETTLEMENT_DAYS),
            } }}
            onChange={(e) => { setSettlementDate(e.target.value); setPlan(null); setDecision(null) }}
            InputLabelProps={{ shrink: true }}
            sx={{
              ...assistantFieldSx(assistantHighlight === 'settlement_date' || assistantHighlight === 'horizon_days') }} />
          <Button variant="contained" size="large" onClick={generate} disabled={busy}
            sx={{ minWidth: 0, height: 40 }}
            startIcon={busy ? <CircularProgress size={16} color="inherit" /> : <PlayArrowOutlinedIcon />}>
            {busy ? 'Generating…' : 'Generate Plan'}
          </Button>
        </Box>
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
            {s.redemption_shortfall_cr > 0 && (
              <Alert severity="warning" variant="outlined">
                <strong>Redemption not fully funded:</strong> requested {fmtCrValue(s.redemption_requested_cr)};
                planned sell orders raise {fmtCrValue(s.redemption_planned_cr)};
                shortfall {fmtCrValue(s.redemption_shortfall_cr)}.
              </Alert>
            )}
            <Stack direction="row" justifyContent="flex-end" sx={{ mb: -1.5 }}>
              <Tooltip title="Close generated plan">
                <IconButton size="small" onClick={closePlan} aria-label="Close generated plan">
                  <CloseIcon fontSize="small" />
                </IconButton>
              </Tooltip>
            </Stack>
            {/* Summary tiles — investable cash leads with an accent */}
            <KpiGrid min={190}>
              <Stat accent icon={<AccountBalanceWalletOutlinedIcon />} label="Investable Cash" value={fmtCrValue(toCr(s.investable_amount), 0)}
                sub={`${plan.intent.trade_date} to ${plan.intent.settlement_date}`} color="secondary.main" />
              <Stat icon={<SwapVertOutlinedIcon />} label="Buy / Sell" value={`${fmtCrValue(toCr(s.total_buy_value), 0)}`}
                sub={`sell ${fmtCrValue(toCr(s.total_sell_value), 0)} · ${s.order_count} orders`} />
              <Stat icon={<AccountBalanceOutlinedIcon />} label="Net Cash Impact" value={fmtCrValue(toCr(s.net_cash_impact), 0)}
                sub={`${s.net_cash_impact < 0 ? 'cash deployed' : 'cash raised'} · ${fmtCrValue(toCr(s.net_cash_after_tax), 0)} after tax`}
                color={s.net_cash_impact < 0 ? 'error.main' : 'success.main'} />
              <Stat icon={<GppGoodOutlinedIcon />} label="Plan Gate" value={<Chip label={planGateStatus} color={sevOf(planGateStatus)} size="small" />}
                sub={`Compliance ${s.compliance_status} · policy ${plan.policy_status}`} />
              {s.total_sell_value > 0 && (
                <Stat icon={<ReceiptLongOutlinedIcon />} label="Est. Exit Tax" value={fmtCrValue(toCr(s.est_total_tax), 2)}
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

            <Alert severity={sevOf(planGateStatus)} variant="outlined">
              <Typography variant="body2">{plan.recommendation}</Typography>
              {planGateStatus === 'BLOCKED' && blockReasons.length > 0 && (
                <Box component="ul" sx={{ mt: 1, mb: 0, pl: 2.5 }}>
                  {blockReasons.map((reason) => (
                    <li key={reason.key}>
                      <Typography variant="body2">
                        <strong>{reason.label}:</strong> {reason.message}
                      </Typography>
                    </li>
                  ))}
                </Box>
              )}
            </Alert>
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
            <GenerationStepsSummary events={progressEvents} />

            {plan.risk_return && (
              <Panel icon={<ShowChartOutlinedIcon />} title="Risk & Return: Before vs After Plan">
                <RiskReturnComparison metrics={plan.risk_return} />
              </Panel>
            )}

            {/* Bento: the generated orders are the hero (wide, highlighted);
                cash-flow + pending context ride a side rail. */}
            <Box sx={{ display: 'grid', gap: 2.5, alignItems: 'start',
              gridTemplateColumns: { xs: '1fr', lg: '1.6fr 1fr' } }}>
              <Panel highlight icon={<ReceiptLongOutlinedIcon />} title={`Generated Orders (${plan.orders.length})`}>
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

                <Panel icon={<AccountBalanceWalletOutlinedIcon />} title={`Cash-Flow Planning → ${fmtCrValue(toCr(plan.cash_flow_planning.investable_amount))}`}>
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

                <Panel icon={<ScheduleOutlinedIcon />} title={`Pending / Unsettled (${plan.pending_trades.length})`}
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
            <Panel icon={<GppGoodOutlinedIcon />} title="Compliance, Tax & Risk">
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
            <Panel highlight icon={<FactCheckOutlinedIcon />} title="PIC Review"
              action={(
                <Stack direction="row" spacing={1} alignItems="center" sx={{ flexWrap: 'wrap' }}>
                  <Chip size="small" label={plan.plan_id} variant="outlined" />
                  <Chip size="small" color="primary" label={decision ? decision.status : plan.status} />
                </Stack>
              )}>
              {!decision ? (
                <Stack direction="row" spacing={1.5} sx={{ flexWrap: 'wrap', gap: 1.5 }}>
                  <Button variant="contained" color="success" startIcon={<CheckCircleIcon />} onClick={() => decide('Approve')}>Approve</Button>
                  <Button variant="outlined" color="error" startIcon={<CloseIcon />} onClick={() => decide('Reject')}>Reject</Button>
                  <Button variant="outlined" color="warning" startIcon={<NorthEastIcon />} onClick={() => decide('Escalate')}>Escalate</Button>
                </Stack>
              ) : (
                <Alert severity="info">
                  <Stack direction={{ xs: 'column', sm: 'row' }} alignItems={{ sm: 'center' }}
                    justifyContent="space-between" spacing={1.5} sx={{ width: '100%' }}>
                    <Box>
                      <Typography variant="body2">Decision recorded: <strong>{decision.decision}</strong> → {decision.status}</Typography>
                      <Typography variant="caption" display="block">by {decision.reviewer} · {new Date(decision.decided_at).toLocaleString()}</Typography>
                    </Box>
                    <Button variant="contained" startIcon={<EmailOutlinedIcon />}
                      onClick={() => onContinueToEmail?.(plan.plan_id)}>
                      Continue to email
                    </Button>
                  </Stack>
                </Alert>
              )}
              <Divider sx={{ my: 1.5 }} />
              <Typography variant="caption" color="text.secondary">
                The engine recommends; a PIC associate decides. Nothing executes without human approval.
              </Typography>
            </Panel>

          </Stack>
        </Grow>
      )}
      </Stack>
    </Box>
  )
}
