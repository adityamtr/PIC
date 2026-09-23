import { useEffect, useState } from 'react'
import {
  Alert, Box, Button, Checkbox, Chip, CircularProgress, Divider, Grow,
  ListItemText, MenuItem, Stack, Step, StepLabel, Stepper, Table, TableBody,
  TableCell, TableHead, TableRow, TextField, ToggleButton, ToggleButtonGroup,
  Typography,
} from '@mui/material'
import CheckCircleIcon from '@mui/icons-material/CheckCircle'
import EditIcon from '@mui/icons-material/EditOutlined'
import CloseIcon from '@mui/icons-material/CloseOutlined'
import NorthEastIcon from '@mui/icons-material/NorthEast'
import { api } from '../api'
import { fmtCrValue, fmtNum, fmtPct, fmtRupee } from '../format'
import { KpiGrid, Panel, ScrollX, Stat } from './ui'

const toCr = (r) => r / 1e7
const STEPS = ['PM Intent', 'Cash-Flow Planning', 'Trade Plan', 'Compliance & Risk', 'PIC Review']

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

const sevOf = (s) => (s === 'FAIL' || s === 'BREACH' || s === 'HIGH' ? 'error'
  : s === 'WARN' || s === 'MEDIUM' ? 'warning' : 'success')

function OrdersTable({ orders }) {
  if (!orders.length) return <Typography color="text.secondary">No orders generated.</Typography>
  return (
    <ScrollX>
      <Table size="small" stickyHeader>
        <TableHead>
          <TableRow>
            <TableCell>Security</TableCell><TableCell>Side</TableCell>
            <TableCell align="right">Shares</TableCell><TableCell align="right">Price</TableCell>
            <TableCell align="right">Est. Value</TableCell>
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
              <TableCell align="right">{fmtNum(o.shares)}</TableCell>
              <TableCell align="right">{fmtRupee(o.price, 0)}</TableCell>
              <TableCell align="right">{fmtCrValue(toCr(o.est_value))}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </ScrollX>
  )
}

export default function TradePlanner({ fundId }) {
  const [action, setAction] = useState('contribution')
  const [amount, setAmount] = useState(250)
  const [targets, setTargets] = useState(['Information Technology'])
  const [horizon, setHorizon] = useState(5)
  const [plan, setPlan] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [decision, setDecision] = useState(null)
  const [fundSectors, setFundSectors] = useState([])

  const cfg = ACTIONS.find((a) => a.key === action)
  // Increase can target any buyable sector; Reduce only sectors the fund holds.
  const sectorOptions = action === 'increase'
    ? BUYABLE_SECTORS
    : (fundSectors.length ? fundSectors : BUYABLE_SECTORS)

  // On fund change: clear any plan and load the fund's sectors for the dropdown.
  useEffect(() => {
    setPlan(null); setDecision(null)
    api.sectorExposure(fundId)
      .then((d) => setFundSectors(d.sectors.map((s) => s.sector)))
      .catch(() => setFundSectors([]))
  }, [fundId])

  // Keep the selected sectors valid for the current action / fund.
  useEffect(() => {
    if (!cfg.needsTarget) return
    const valid = targets.filter((t) => sectorOptions.includes(t))
    if (valid.length === 0) setTargets([sectorOptions[0]])
    else if (valid.length !== targets.length) setTargets(valid)
  }, [action, fundSectors]) // eslint-disable-line react-hooks/exhaustive-deps

  function applyPreset(p) {
    setAction(p.action)
    if (p.amount_cr != null) setAmount(p.amount_cr)
    if (p.targets) setTargets(p.targets)
    setPlan(null); setDecision(null)
  }

  async function generate() {
    setBusy(true); setError(null); setDecision(null); setPlan(null)
    try {
      const payload = {
        action,
        amount_cr: cfg.needsAmount ? Number(amount) : undefined,
        targets: cfg.needsTarget ? targets : undefined,
        horizon_days: Number(horizon),
        fund_id: fundId,
      }
      setPlan(await api.createTradePlan(payload))
    } catch (e) { setError(e.message) } finally { setBusy(false) }
  }

  async function decide(choice) {
    if (!plan) return
    try {
      setDecision(await api.decide(plan.plan_id, { decision: choice, reviewer: 'PIC Associate' }))
    } catch (e) { setError(e.message) }
  }

  const s = plan?.summary
  const activeStep = plan ? 4 : 0

  return (
    <Stack spacing={2.5}>
      <Stepper activeStep={activeStep} alternativeLabel sx={{ display: { xs: 'none', md: 'flex' } }}>
        {STEPS.map((label) => <Step key={label}><StepLabel>{label}</StepLabel></Step>)}
      </Stepper>

      {/* Intent — the input, given a highlighted card at the top */}
      <Panel highlight title="Portfolio Manager Intent">
        <ToggleButtonGroup exclusive value={action} color="primary" size="small"
          onChange={(_, v) => v && (setAction(v), setPlan(null), setDecision(null))}
          sx={{ flexWrap: 'wrap', mb: 2 }}>
          {ACTIONS.map((a) => <ToggleButton key={a.key} value={a.key}>{a.label}</ToggleButton>)}
        </ToggleButtonGroup>

        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} alignItems={{ sm: 'flex-end' }}>
          {cfg.needsTarget && (
            <TextField label="Sectors" size="small" select
              value={targets.filter((t) => sectorOptions.includes(t))}
              onChange={(e) => setTargets(
                typeof e.target.value === 'string' ? e.target.value.split(',') : e.target.value)}
              helperText={targets.length > 1 ? `Amount split evenly across ${targets.length} sectors` : ' '}
              sx={{ minWidth: 260 }}
              SelectProps={{
                multiple: true,
                renderValue: (sel) => sel.join(', '),
              }}>
              {sectorOptions.map((sc) => (
                <MenuItem key={sc} value={sc}>
                  <Checkbox size="small" checked={targets.indexOf(sc) > -1} />
                  <ListItemText primary={sc} />
                </MenuItem>
              ))}
            </TextField>
          )}
          {cfg.needsAmount && (
            <TextField label="Amount (₹ Cr)" size="small" type="number" value={amount}
              onChange={(e) => setAmount(e.target.value)} sx={{ minWidth: 150 }} />
          )}
          <TextField label="Horizon" size="small" select value={horizon}
            onChange={(e) => setHorizon(e.target.value)} sx={{ minWidth: 130 }}>
            {[3, 5, 10, 15].map((d) => <MenuItem key={d} value={d}>{d} business days</MenuItem>)}
          </TextField>
          <Button variant="contained" size="large" onClick={generate} disabled={busy}
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

      {error && <Alert severity="error">{error} — is the backend running on :8000?</Alert>}

      {plan && (
        <Grow in timeout={450}>
          <Stack spacing={2.5}>
            {/* Summary tiles — investable cash leads with an accent */}
            <KpiGrid min={190}>
              <Stat accent label="Investable Cash" value={fmtCrValue(toCr(s.investable_amount), 0)}
                sub={`over ${plan.intent.horizon_days} business days`} color="secondary.main" />
              <Stat label="Buy / Sell" value={`${fmtCrValue(toCr(s.total_buy_value), 0)}`}
                sub={`sell ${fmtCrValue(toCr(s.total_sell_value), 0)} · ${s.order_count} orders`} />
              <Stat label="Net Cash Impact" value={fmtCrValue(toCr(s.net_cash_impact), 0)}
                sub={s.net_cash_impact < 0 ? 'cash deployed' : 'cash raised'}
                color={s.net_cash_impact < 0 ? 'error.main' : 'success.main'} />
              <Stat label="Compliance" value={<Chip label={s.compliance_status} color={sevOf(s.compliance_status)} size="small" />}
                sub={decision ? decision.status : plan.status} />
            </KpiGrid>

            <Alert severity={sevOf(s.compliance_status)} variant="outlined">{plan.recommendation}</Alert>
            {plan.warnings?.map((w, i) => <Alert key={i} severity="warning">{w}</Alert>)}

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

            {/* Compliance & Risk — split two-up; needs the full width */}
            <Panel title="Compliance Checks & Risk Flags">
              <Box sx={{ display: 'grid', gap: 3, gridTemplateColumns: { xs: '1fr', md: '1.4fr 1fr' } }}>
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
                  <Typography variant="subtitle2" gutterBottom>Execution Risk</Typography>
                  {plan.risk_flags.length === 0 ? <Typography color="text.secondary" variant="body2">No material execution risks.</Typography> : (
                    <Stack spacing={1}>
                      {plan.risk_flags.map((r, i) => (
                        <Alert key={i} severity={sevOf(r.severity)} variant="outlined" sx={{ py: 0 }}>
                          <strong>{r.type}</strong> — {r.message}
                        </Alert>
                      ))}
                    </Stack>
                  )}
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
          </Stack>
        </Grow>
      )}
    </Stack>
  )
}
