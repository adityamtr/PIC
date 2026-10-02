import { useEffect, useState } from 'react'
import {
  Accordion, AccordionDetails, AccordionSummary, Alert, Box, Button, Chip,
  CircularProgress, Dialog, DialogActions, DialogContent, DialogTitle, Divider,
  IconButton, MenuItem, Stack, Table, TableBody, TableCell, TableHead, TableRow,
  Snackbar, TextField, ToggleButton, ToggleButtonGroup, Tooltip, Typography,
} from '@mui/material'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import EmailOutlinedIcon from '@mui/icons-material/EmailOutlined'
import HistoryIcon from '@mui/icons-material/History'
import SendOutlinedIcon from '@mui/icons-material/SendOutlined'
import CheckCircleIcon from '@mui/icons-material/CheckCircle'
import CloseIcon from '@mui/icons-material/CloseOutlined'
import NorthEastIcon from '@mui/icons-material/NorthEast'
import ReactMarkdown from 'react-markdown'
import { api } from '../api'
import { fmtCrValue, fmtNum, fmtRupee } from '../format'
import { Panel } from './ui'

const toCr = (rupees) => (rupees == null ? null : rupees / 1e7)
const formatReturn = (value) => (value == null ? '—' : `${(value * 100).toFixed(2)}%`)
const formatDate = (value) => {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}
const riskGroupLabels = {
  country: 'Portfolio exposure',
  liquidity: 'Execution liquidity',
  timing: 'Market timing',
  lock_in: 'Lock-in constraints',
  plan_creation: 'Plan validation',
  taxation: 'Tax impact',
}

function summarizeRiskFlags(flags) {
  const findings = new Map()
  for (const flag of flags) {
    const category = flag.type || 'other'
    const severity = flag.severity || 'MEDIUM'
    const message = flag.message || 'No description provided.'
    const key = JSON.stringify([category, severity, message])
    const finding = findings.get(key) || {
      category,
      severity,
      message,
      count: 0,
      affected: new Set(),
    }
    finding.count += 1
    if (flag.ticker || flag.entity) finding.affected.add(flag.ticker || flag.entity)
    findings.set(key, finding)
  }
  return [...findings.values()].map((finding) => ({
    ...finding,
    affected: [...finding.affected],
  }))
}

function decisionStatus(plan) {
  const rawStatus = (plan.status || '').toLowerCase()
  const decision = (plan.decision?.decision || '').toLowerCase()
  if (rawStatus.includes('approv') || decision === 'approve') return { label: 'Approved', color: 'success' }
  if (rawStatus.includes('reject') || decision === 'reject') return { label: 'Rejected', color: 'error' }
  if (rawStatus.includes('escalat') || decision === 'escalate') return { label: 'Escalated', color: 'warning' }
  if (rawStatus.includes('modification') || decision === 'modify') return { label: 'Changes requested', color: 'info' }
  return { label: 'Pending review', color: 'default' }
}

function PlanOrders({ orders = [] }) {
  if (!orders.length) return <Typography variant="body2" color="text.secondary">No orders in this plan.</Typography>
  return (
    <Box sx={{ overflowX: 'auto' }}>
      <Table size="small">
        <TableHead>
          <TableRow>
            <TableCell>Security</TableCell>
            <TableCell>Side</TableCell>
            <TableCell align="right">Shares</TableCell>
            <TableCell align="right">Price</TableCell>
            <TableCell align="right">Est. Value</TableCell>
            <TableCell align="right">Expected Return</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {orders.map((order, index) => (
            <TableRow key={`${order.ticker}-${index}`} hover>
              <TableCell>
                <Typography variant="body2" fontWeight={700}>{order.ticker}</Typography>
                <Typography variant="caption" color="text.secondary">{order.sector || order.name}</Typography>
              </TableCell>
              <TableCell>
                <Chip size="small" variant="outlined" label={order.side}
                  color={order.side === 'BUY' ? 'success' : 'error'} />
              </TableCell>
              <TableCell align="right">{fmtNum(order.shares)}</TableCell>
              <TableCell align="right">{fmtRupee(order.price, 0)}</TableCell>
              <TableCell align="right">{fmtCrValue(toCr(order.est_value))}</TableCell>
              <TableCell align="right">{formatReturn(order.expected_return)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Box>
  )
}

function PlanRecord({ plan, onDecide, deciding, onGenerateEmail, onViewEmails, generatingEmail,
  expanded, onExpandedChange }) {
  const status = decisionStatus(plan)
  const intent = plan.intent || {}
  const summary = plan.summary || {}
  const target = Array.isArray(intent.targets) ? intent.targets.join(', ') : intent.target
  const method = plan.allocation_method || intent.method || '—'
  const pendingReview = status.label === 'Pending review'
  const decisionComplete = ['Approved', 'Rejected', 'Escalated'].includes(status.label)
  const sentEmailCount = plan.sent_email_count || 0
  const riskFlags = plan.risk_flags || []
  const riskFindings = summarizeRiskFlags(riskFlags)
  const riskGroups = riskFindings.reduce((groups, finding) => {
    groups[finding.category] = [...(groups[finding.category] || []), finding]
    return groups
  }, {})
  const highRiskCount = riskFindings.filter((finding) => finding.severity === 'HIGH').length
  const reviewRiskCount = riskFindings.filter((finding) => finding.severity === 'MEDIUM').length

  return (
    <Accordion id={`plan-record-${plan.plan_id}`} expanded={expanded}
      onChange={(_, isExpanded) => onExpandedChange(isExpanded ? plan.plan_id : '')}
      disableGutters elevation={0} sx={{
      border: 1, borderColor: 'divider', borderRadius: '4px !important',
      '&:before': { display: 'none' },
    }}>
      <AccordionSummary expandIcon={<ExpandMoreIcon />} sx={{ px: 2, minHeight: 68 }}>
        <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', sm: 'minmax(0, 1fr) auto' },
          alignItems: 'center', gap: 1.25, width: '100%', pr: 1 }}>
          <Box sx={{ minWidth: 0 }}>
            <Typography variant="subtitle2" fontWeight={700} sx={{ overflowWrap: 'anywhere' }}>
              Plan {plan.plan_id}
            </Typography>
            <Typography variant="caption" color="text.secondary">
              {formatDate(plan.created_at)} · {intent.action ? intent.action.replaceAll('_', ' ') : 'Trade plan'}
              {target ? ` · ${target}` : ''} · {summary.order_count ?? plan.orders?.length ?? 0} orders
            </Typography>
          </Box>
          <Stack direction="row" spacing={0.75} sx={{ flexWrap: 'wrap', gap: 0.75 }}>
            <Chip size="small" color={status.color} label={status.label} />
            {sentEmailCount > 0 && (
              <Tooltip title={`Last sent ${formatDate(plan.last_sent_email_at)}`}>
                <Chip size="small" color="success" variant="outlined" icon={<EmailOutlinedIcon />}
                  label={sentEmailCount === 1 ? 'Email sent' : `${sentEmailCount} emails sent`} />
              </Tooltip>
            )}
          </Stack>
        </Box>
      </AccordionSummary>
      <AccordionDetails sx={{ px: { xs: 1.5, sm: 2 }, pt: 0, pb: 2 }}>
        <Stack spacing={2}>
          <Divider />
          <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr 1fr', md: 'repeat(4, minmax(0, 1fr))' }, gap: 1.5 }}>
            <Box><Typography variant="caption" color="text.secondary">Request</Typography>
              <Typography variant="body2" fontWeight={600}>{intent.action || '—'}</Typography></Box>
            <Box><Typography variant="caption" color="text.secondary">Amount</Typography>
              <Typography variant="body2" fontWeight={600}>{intent.amount_cr == null ? '—' : fmtCrValue(intent.amount_cr)}</Typography></Box>
            <Box><Typography variant="caption" color="text.secondary">Trade / Settlement</Typography>
              <Typography variant="body2" fontWeight={600}>{intent.trade_date || '—'} / {intent.settlement_date || '—'}</Typography></Box>
            <Box><Typography variant="caption" color="text.secondary">Allocation</Typography>
              <Typography variant="body2" fontWeight={600}>{method}</Typography></Box>
            <Box><Typography variant="caption" color="text.secondary">Buy Value</Typography>
              <Typography variant="body2" fontWeight={600}>{fmtCrValue(toCr(summary.total_buy_value))}</Typography></Box>
            <Box><Typography variant="caption" color="text.secondary">Sell Value</Typography>
              <Typography variant="body2" fontWeight={600}>{fmtCrValue(toCr(summary.total_sell_value))}</Typography></Box>
            <Box><Typography variant="caption" color="text.secondary">Compliance</Typography>
              <Typography variant="body2" fontWeight={600}>{summary.compliance_status || '—'}</Typography></Box>
            <Box><Typography variant="caption" color="text.secondary">Execution</Typography>
              <Typography variant="body2" fontWeight={600}>{plan.execution_allowed ? 'Allowed' : 'Review required'}</Typography></Box>
          </Box>

          <Box>
            <Typography variant="subtitle2" sx={{ mb: 0.75 }}>Generated Orders ({plan.orders?.length || 0})</Typography>
            <PlanOrders orders={plan.orders} />
          </Box>

          {plan.decision && (
            <Box sx={{ borderLeft: 3, borderColor: 'primary.main', pl: 1.5 }}>
              <Typography variant="subtitle2">PIC Review</Typography>
              <Typography variant="body2" color="text.secondary">
                {plan.decision.decision} by {plan.decision.reviewer || 'reviewer'} · {formatDate(plan.decision.decided_at)}
              </Typography>
              {plan.decision.comment && <Typography variant="body2" sx={{ mt: 0.5 }}>{plan.decision.comment}</Typography>}
            </Box>
          )}

          {riskFlags.length > 0 && (
            <Accordion disableGutters elevation={0} defaultExpanded={riskFlags.length <= 5}
              sx={{ border: 1, borderColor: 'divider', borderRadius: 1, '&:before': { display: 'none' } }}>
              <AccordionSummary expandIcon={<ExpandMoreIcon />} sx={{ px: 1.5 }}>
                <Stack direction="row" alignItems="center" spacing={1} sx={{ flexWrap: 'wrap', pr: 1 }}>
                  <Typography variant="subtitle2">Risk review</Typography>
                  <Chip size="small" variant="outlined" label={`${riskFlags.length} flags`} />
                  {riskFindings.length < riskFlags.length && (
                    <Chip size="small" variant="outlined" label={`${riskFindings.length} distinct findings`} />
                  )}
                  {highRiskCount > 0 && <Chip size="small" color="error" variant="outlined" label={`${highRiskCount} high`} />}
                  {reviewRiskCount > 0 && <Chip size="small" color="warning" variant="outlined" label={`${reviewRiskCount} review`} />}
                </Stack>
              </AccordionSummary>
              <AccordionDetails sx={{ px: 1.5, pt: 0 }}>
                <Stack spacing={1.5}>
                  {Object.entries(riskGroups).map(([category, findings]) => (
                    <Box key={category}>
                      <Typography variant="caption" color="text.secondary" fontWeight={700}>
                        {riskGroupLabels[category] || category.replaceAll('_', ' ')}
                      </Typography>
                      <Stack divider={<Divider flexItem />}>
                        {findings.map((finding) => (
                          <Stack key={`${finding.category}-${finding.severity}-${finding.message}`}
                            direction={{ xs: 'column', sm: 'row' }} alignItems={{ sm: 'flex-start' }}
                            spacing={0.75} sx={{ py: 1 }}>
                            <Chip size="small" label={finding.severity} variant="outlined"
                              color={finding.severity === 'HIGH' ? 'error' : finding.severity === 'MEDIUM' ? 'warning' : 'default'} />
                            <Box sx={{ flex: 1, minWidth: 0 }}>
                              <Typography variant="body2">{finding.message}</Typography>
                              {finding.affected.length > 0 && (
                                <Typography variant="caption" color="text.secondary">
                                  Affected: {finding.affected.slice(0, 5).join(', ')}
                                  {finding.affected.length > 5 ? `, +${finding.affected.length - 5} more` : ''}
                                </Typography>
                              )}
                            </Box>
                            {finding.count > 1 && (
                              <Chip size="small" variant="outlined" label={`${finding.count} occurrences`} />
                            )}
                          </Stack>
                        ))}
                      </Stack>
                    </Box>
                  ))}
                </Stack>
              </AccordionDetails>
            </Accordion>
          )}

          <Divider />
          <Stack direction={{ xs: 'column', sm: 'row' }} alignItems={{ sm: 'center' }}
            justifyContent="space-between" spacing={1}>
            <Typography variant="subtitle2">PIC Review</Typography>
            <Stack direction="row" sx={{ flexWrap: 'wrap', gap: 0.75 }}>
              <Button size="small" variant="contained" color="success"
                startIcon={deciding ? <CircularProgress size={14} color="inherit" /> : <CheckCircleIcon />}
                disabled={!pendingReview || deciding} onClick={() => onDecide(plan, 'Approve')}>
                Approve
              </Button>
              <Button size="small" variant="outlined" color="error" startIcon={<CloseIcon />}
                disabled={!pendingReview || deciding} onClick={() => onDecide(plan, 'Reject')}>
                Reject
              </Button>
              <Button size="small" variant="outlined" color="warning" startIcon={<NorthEastIcon />}
                disabled={!pendingReview || deciding} onClick={() => onDecide(plan, 'Escalate')}>
                Escalate
              </Button>
              <Button size="small" variant="contained" color="primary"
                startIcon={generatingEmail ? <CircularProgress size={14} color="inherit" /> : <EmailOutlinedIcon />}
                disabled={!decisionComplete || generatingEmail} onClick={() => onGenerateEmail(plan)}>
                {generatingEmail ? 'Drafting…' : 'Draft Email'}
              </Button>
              <Button size="small" variant="outlined" startIcon={<HistoryIcon />}
                disabled={!decisionComplete} onClick={() => onViewEmails(plan)}>
                Email History
              </Button>
            </Stack>
          </Stack>
        </Stack>
      </AccordionDetails>
    </Accordion>
  )
}

export default function PlanHistory({ fundId, focusPlanId = '' }) {
  const [plans, setPlans] = useState([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [actionError, setActionError] = useState('')
  const [deciding, setDeciding] = useState('')
  const [expandedPlanId, setExpandedPlanId] = useState(focusPlanId)
  const [generatingEmail, setGeneratingEmail] = useState('')
  const [emailDraft, setEmailDraft] = useState(null)
  const [sentEmails, setSentEmails] = useState([])
  const [emailPlanId, setEmailPlanId] = useState('')
  const [sendingEmail, setSendingEmail] = useState(false)
  const [draftOpen, setDraftOpen] = useState(false)
  const [emailDialogMode, setEmailDialogMode] = useState('compose')
  const [sentNotice, setSentNotice] = useState('')
  const [copyStatus, setCopyStatus] = useState('')
  const [bodyMode, setBodyMode] = useState('preview')

  useEffect(() => {
    let active = true
    setLoading(true)
    setLoadError('')
    api.tradePlans(fundId)
      .then((response) => { if (active) setPlans(response.plans || []) })
      .catch((error) => { if (active) setLoadError(error.message) })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [fundId])

  useEffect(() => {
    setExpandedPlanId(focusPlanId)
    if (focusPlanId && !loading) {
      document.getElementById(`plan-record-${focusPlanId}`)?.scrollIntoView({
        behavior: 'smooth',
        block: 'center',
      })
    }
  }, [focusPlanId, loading, plans])

  async function decide(plan, choice) {
    setDeciding(plan.plan_id)
    setActionError('')
    try {
      const result = await api.decide(plan.plan_id, { decision: choice, reviewer: 'PIC Associate' })
      setPlans((current) => current.map((item) => item.plan_id === plan.plan_id
        ? { ...item, status: result.status, decision: {
          decision: result.decision,
          reviewer: result.reviewer,
          comment: result.comment,
          decided_at: result.decided_at,
        } }
        : item))
    } catch (error) {
      setActionError(error.message)
    } finally {
      setDeciding('')
    }
  }

  async function generateEmail(plan) {
    setGeneratingEmail(plan.plan_id)
    setActionError('')
    try {
      const draft = await api.generatePlanEmail(plan.plan_id)
      setEmailPlanId(plan.plan_id)
      setSentEmails([])
      setEmailDraft(draft)
      setCopyStatus('')
      setBodyMode('preview')
      setEmailDialogMode('compose')
      setDraftOpen(true)
    } catch (error) {
      setActionError(error.message)
    } finally {
      setGeneratingEmail('')
    }
  }

  async function viewEmailHistory(plan) {
    setActionError('')
    try {
      const result = await api.planSentEmails(plan.plan_id)
      setEmailPlanId(plan.plan_id)
      setSentEmails(result.emails || [])
      setEmailDraft(result.emails?.[0] || null)
      setCopyStatus('')
      setBodyMode('preview')
      setEmailDialogMode('history')
      setDraftOpen(true)
    } catch (error) {
      setActionError(error.message)
    }
  }

  async function sendEmailDraft() {
    if (!emailDraft || !emailPlanId || emailDialogMode !== 'compose') return
    setSendingEmail(true)
    setCopyStatus('')
    try {
      const sent = await api.sendPlanEmail(emailPlanId, {
        subject: emailDraft.subject,
        body: emailDraft.body,
        model: emailDraft.model,
      })
      setSentEmails((current) => [sent, ...current.filter((email) => email.email_id !== sent.email_id)])
      setPlans((current) => current.map((plan) => plan.plan_id === emailPlanId
        ? {
          ...plan,
          sent_email_count: (plan.sent_email_count || 0) + 1,
          last_sent_email_at: sent.sent_at,
        }
        : plan))
      setEmailDraft(null)
      setDraftOpen(false)
      setSentNotice('Sent to this plan’s email history. External delivery is not configured.')
    } catch (error) {
      setActionError(error.message)
    } finally {
      setSendingEmail(false)
    }
  }

  async function copyEmailDraft() {
    if (!emailDraft) return
    try {
      await navigator.clipboard.writeText(`Subject: ${emailDraft.subject}\n\n${emailDraft.body}`)
      setCopyStatus('Copied')
    } catch {
      setCopyStatus('Clipboard access unavailable')
    }
  }

  return (
    <Stack spacing={2}>
      <Panel title="Generated Plans" subtitle="Plans for the selected fund, newest first. Expand a plan to review details and take action.">
        {loading ? (
          <Box sx={{ display: 'flex', justifyContent: 'center', py: 5 }}><CircularProgress size={26} /></Box>
        ) : loadError ? (
          <Alert severity="error">Could not load plan history: {loadError}</Alert>
        ) : plans.length === 0 ? (
          <Typography variant="body2" color="text.secondary" sx={{ py: 2 }}>No generated plans for this fund yet.</Typography>
        ) : (
          <Stack spacing={1}>
            {actionError && <Alert severity="error" onClose={() => setActionError('')}>{actionError}</Alert>}
            {plans.map((plan) => (
              <PlanRecord key={plan.plan_id} plan={plan} onDecide={decide}
                deciding={deciding === plan.plan_id} onGenerateEmail={generateEmail}
                onViewEmails={viewEmailHistory}
                generatingEmail={generatingEmail === plan.plan_id}
                expanded={expandedPlanId === plan.plan_id} onExpandedChange={setExpandedPlanId} />
            ))}
          </Stack>
        )}
      </Panel>
      <Dialog open={draftOpen} onClose={() => setDraftOpen(false)} fullWidth maxWidth="md">
        <DialogTitle sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          {emailDialogMode === 'compose' ? 'Email Draft' : 'Sent Email History'}
          <IconButton aria-label="Close email draft" onClick={() => setDraftOpen(false)} size="small">
            <CloseIcon />
          </IconButton>
        </DialogTitle>
        <DialogContent dividers>
          <Stack spacing={1.5}>
            <Alert severity="info">
              {emailDialogMode === 'compose'
                ? `Review the draft before sending. It will appear in this plan’s history; external delivery is not configured.`
                : 'These emails were marked sent from this plan. External delivery is not configured.'}
            </Alert>
            {emailDialogMode === 'history' && sentEmails.length === 0 && (
              <Typography variant="body2" color="text.secondary" sx={{ py: 2 }}>
                No emails have been sent from this plan yet.
              </Typography>
            )}
            {sentEmails.length > 0 && (
              <TextField select label="Sent emails" value={emailDraft?.email_id || ''} fullWidth
                onChange={(event) => setEmailDraft(sentEmails.find(
                  (email) => email.email_id === event.target.value) || null)}>
                {sentEmails.map((email) => (
                  <MenuItem key={email.email_id} value={email.email_id}>
                    {formatDate(email.sent_at)} · {email.subject}
                  </MenuItem>
                ))}
              </TextField>
            )}
            {emailDraft && (
              <>
                <TextField label="Subject" value={emailDraft.subject} fullWidth
                  InputProps={{ readOnly: emailDialogMode === 'history' }}
                  onChange={(event) => setEmailDraft((current) => ({ ...current, subject: event.target.value }))} />
                {emailDialogMode === 'compose' && (
                  <Stack direction="row" alignItems="center" justifyContent="space-between">
                    <Typography variant="subtitle2">Body</Typography>
                    <ToggleButtonGroup size="small" exclusive value={bodyMode} aria-label="Email body mode"
                      onChange={(_, value) => value && setBodyMode(value)}>
                      <ToggleButton value="edit">Edit</ToggleButton>
                      <ToggleButton value="preview">Preview</ToggleButton>
                    </ToggleButtonGroup>
                  </Stack>
                )}
                {emailDialogMode === 'compose' && bodyMode === 'edit' ? (
                  <TextField label="Markdown body" value={emailDraft.body} fullWidth multiline minRows={12}
                    onChange={(event) => setEmailDraft((current) => ({ ...current, body: event.target.value }))} />
                ) : (
                  <Box component="article" sx={{
                    minHeight: 280,
                    maxHeight: 460,
                    overflowY: 'auto',
                    overflowWrap: 'anywhere',
                    px: 2,
                    py: 1.5,
                    border: 1,
                    borderColor: 'divider',
                    borderRadius: 1,
                    '& h1, & h2, & h3': { mt: 2, mb: 1, fontWeight: 700, lineHeight: 1.3 },
                    '& h1': { fontSize: '1.25rem' },
                    '& h2': { fontSize: '1.1rem' },
                    '& h3': { fontSize: '1rem' },
                    '& p': { my: 1 },
                    '& ul, & ol': { pl: 3, my: 1 },
                    '& li': { mb: 0.5 },
                    '& > :first-of-type': { mt: 0 },
                  }}>
                    <ReactMarkdown>{emailDraft.body}</ReactMarkdown>
                  </Box>
                )}
              </>
            )}
            {copyStatus && <Typography variant="caption" color="text.secondary">{copyStatus}</Typography>}
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={copyEmailDraft} disabled={!emailDraft}>Copy email</Button>
          {emailDialogMode === 'compose' && (
            <Button onClick={sendEmailDraft} disabled={!emailDraft || sendingEmail} variant="contained"
              startIcon={sendingEmail ? <CircularProgress size={14} color="inherit" /> : <SendOutlinedIcon />}>
              Send
            </Button>
          )}
        </DialogActions>
      </Dialog>
      <Snackbar open={Boolean(sentNotice)} autoHideDuration={5000} onClose={() => setSentNotice('')}>
        <Alert severity="success" variant="filled" onClose={() => setSentNotice('')}>
          {sentNotice}
        </Alert>
      </Snackbar>
    </Stack>
  )
}