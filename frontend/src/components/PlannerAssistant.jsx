import { useEffect, useRef, useState } from 'react'
import {
  Alert, Box, Button, Chip, CircularProgress, Dialog, DialogActions, DialogContent,
  DialogTitle, Divider, IconButton, Menu, MenuItem, Paper, Stack, TextField, Tooltip, Typography,
} from '@mui/material'
import AutoAwesomeOutlinedIcon from '@mui/icons-material/AutoAwesomeOutlined'
import ClearAllOutlinedIcon from '@mui/icons-material/ClearAllOutlined'
import CloseFullscreenOutlinedIcon from '@mui/icons-material/CloseFullscreenOutlined'
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutlineOutlined'
import HistoryOutlinedIcon from '@mui/icons-material/HistoryOutlined'
import OpenInFullOutlinedIcon from '@mui/icons-material/OpenInFullOutlined'
import SendOutlinedIcon from '@mui/icons-material/SendOutlined'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { api } from '../api'

const FIELD_LABELS = {
  action: 'Action', amount_cr: 'Amount', targets: 'Sector', method: 'Approach',
  fund_id: 'Fund', horizon_days: 'Horizon', trade_date: 'Trade date',
  settlement_date: 'Settlement date', target_volatility: 'Risk target',
}

const MAX_SUGGESTIONS = 2
const SESSION_KEY = 'pic-assistant-chat-session'
const ARCHIVE_KEY = 'pic-assistant-chat-archive'
const MAX_ARCHIVED_SESSIONS = 20

function loadSession() {
  try {
    const raw = window.sessionStorage.getItem(SESSION_KEY)
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

// Past conversations survive "Clear chat" (and the browser tab closing) so
// the user can come back and reopen one later — kept in localStorage rather
// than the per-tab sessionStorage used for the live conversation.
function loadArchive() {
  try {
    const raw = window.localStorage.getItem(ARCHIVE_KEY)
    const parsed = raw ? JSON.parse(raw) : []
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

function saveArchive(sessions) {
  try {
    window.localStorage.setItem(ARCHIVE_KEY, JSON.stringify(sessions))
  } catch {
    // localStorage unavailable (private mode, quota) — archive just won't persist.
  }
}

function sessionTitle(messages) {
  const firstUser = messages.find((item) => item.role === 'user')
  if (!firstUser) return 'Untitled conversation'
  return firstUser.content.length > 48 ? `${firstUser.content.slice(0, 48)}…` : firstUser.content
}

// Shown only before the first message, when there's no chat yet to generate
// real suggestions from. Once a reply comes back, the model's own
// conversation-grounded suggestions (see `suggestedPrompts`) take over.
function starterPrompts(plan, funds, fundId) {
  if (plan?.plan_id) {
    return ['Can you explain this plan in simple terms?', 'Which orders are the biggest?'].slice(0, MAX_SUGGESTIONS)
  }
  const current = funds.find((fund) => fund.fund_id === fundId) || funds[0]
  const other = funds.find((fund) => fund.fund_id !== current?.fund_id)
  const prompts = []
  if (current) prompts.push(`Redeem ₹10 Cr from ${current.name}`)
  prompts.push(other
    ? `Switch to ${other.name} and rebalance it for me`
    : 'Build me a plan to invest ₹250 Cr, optimized automatically')
  return prompts.slice(0, MAX_SUGGESTIONS)
}

function displayValue(key, value, funds) {
  if (key === 'fund_id') return funds.find((fund) => fund.fund_id === value)?.name || value
  if (key === 'amount_cr') return `₹${value} Cr`
  if (key === 'target_volatility') return `${(Number(value) * 100).toFixed(1)}%`
  if (key === 'targets') return value.join(', ')
  if (key === 'manual_selections') {
    return value.map((item) => `${item.side} ${item.ticker} ₹${item.amount_cr} Cr`).join(', ')
  }
  if (key === 'manual_sector_selections') {
    return value.map((item) => `${item.sector} ₹${item.amount_cr} Cr`).join(', ')
  }
  if (key === 'horizon_days') return `${value} days`
  return String(value)
}

export default function PlannerAssistant({
  fundId, funds, draft, sectors, securities, plan, onApplyUpdates, onGeneratePlan, busy,
}) {
  const [messages, setMessages] = useState(() => loadSession()?.messages || [])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState('')
  const [confirmation, setConfirmation] = useState(null)
  const [generating, setGenerating] = useState(false)
  const [fullPage, setFullPage] = useState(false)
  const [suggestedPrompts, setSuggestedPrompts] = useState(() => loadSession()?.suggestedPrompts || [])
  const [pastSessions, setPastSessions] = useState(() => loadArchive())
  const [sessionsAnchor, setSessionsAnchor] = useState(null)
  const endRef = useRef(null)
  const previousPlanId = useRef(null)

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages, sending])

  // Persist the conversation for the lifetime of the browser tab, so a reload
  // recalls prior messages — only "Clear chat" actually resets it.
  useEffect(() => {
    try {
      window.sessionStorage.setItem(SESSION_KEY, JSON.stringify({ messages, suggestedPrompts }))
    } catch {
      // sessionStorage unavailable (private mode, quota) — chat still works in-memory.
    }
  }, [messages, suggestedPrompts])

  useEffect(() => {
    const nextPlanId = plan?.plan_id || null
    if (nextPlanId && nextPlanId !== previousPlanId.current) {
      setMessages((current) => [...current, {
        id: `${Date.now()}-plan`, role: 'assistant',
        content: 'The plan is ready for review. I can explain the summary, inspect policy and compliance findings, or look up specific orders. I cannot modify or approve it.',
      }])
    }
    previousPlanId.current = nextPlanId
  }, [plan?.plan_id])

  const addMessage = (message) => setMessages((current) => [...current, {
    id: `${Date.now()}-${Math.random()}`, ...message,
  }])

  async function submit(text = input) {
    const message = text.trim()
    if (!message || sending || busy) return
    const history = messages
      .filter((item) => item.role === 'user' || item.role === 'assistant')
      .map(({ role, content }) => ({ role, content }))
      .slice(-10)
    addMessage({ role: 'user', content: message })
    setInput('')
    setError('')
    setSuggestedPrompts([])
    setSending(true)
    try {
      if (plan?.plan_id) {
        const result = await api.assistantChat(plan.plan_id, message, history)
        addMessage({ role: 'assistant', content: result.reply, toolsUsed: result.tools_used })
        setSuggestedPrompts((result.suggested_prompts || []).slice(0, MAX_SUGGESTIONS))
      } else {
        const result = await api.interpretIntent({
          message,
          draft,
          history,
        })
        if (Object.keys(result.updates || {}).length) {
          await onApplyUpdates(result.updates)
        }
        addMessage({
          role: 'assistant', content: result.reply, updates: result.updates,
          readyToGenerate: result.ready_to_generate,
          requestedText: message,
        })
        setSuggestedPrompts((result.suggested_prompts || []).slice(0, MAX_SUGGESTIONS))
      }
    } catch (requestError) {
      setError(requestError.message || 'The assistant could not complete this request.')
    } finally {
      setSending(false)
    }
  }

  async function confirmGenerate() {
    setConfirmation(null)
    setGenerating(true)
    try {
      await onGeneratePlan()
    } finally {
      setGenerating(false)
    }
  }

  // Stashes the live conversation into the archive so it's not lost when
  // clearing or switching to a previously saved session.
  function archiveCurrentSession() {
    if (!messages.length) return
    const archived = {
      id: `${Date.now()}`,
      savedAt: Date.now(),
      title: sessionTitle(messages),
      messages,
      suggestedPrompts,
    }
    setPastSessions((current) => {
      const next = [archived, ...current].slice(0, MAX_ARCHIVED_SESSIONS)
      saveArchive(next)
      return next
    })
  }

  function clearChat() {
    archiveCurrentSession()
    setMessages([])
    setInput('')
    setError('')
    setConfirmation(null)
    setSuggestedPrompts([])
    try { window.sessionStorage.removeItem(SESSION_KEY) } catch { /* ignore */ }
  }

  function openPastSession(session) {
    archiveCurrentSession()
    setMessages(session.messages)
    setSuggestedPrompts(session.suggestedPrompts || [])
    setInput('')
    setError('')
    setConfirmation(null)
    setSessionsAnchor(null)
  }

  function deletePastSession(id) {
    setPastSessions((current) => {
      const next = current.filter((session) => session.id !== id)
      saveArchive(next)
      return next
    })
  }

  const displayedPrompts = messages.length === 0 ? starterPrompts(plan, funds, fundId) : suggestedPrompts

  return (
    <Paper component="aside" variant="outlined" sx={(theme) => ({
      position: fullPage ? 'fixed' : { lg: 'sticky' },
      ...(fullPage
        ? { inset: 0, zIndex: theme.zIndex.modal + 1, width: '100vw', height: '100dvh' }
        : { top: { lg: 88 }, minHeight: { xs: 440, lg: 'calc(100vh - 112px)' },
          maxHeight: { lg: 'calc(100vh - 112px)' } }),
      display: 'flex', flexDirection: 'column', minWidth: 0,
      overflow: 'hidden', borderColor: 'divider', borderRadius: fullPage ? 0 : 1,
      gridArea: 'assistant',
    })}>
      <Box sx={{ px: 2, py: 1.5, bgcolor: 'background.paper' }}>
        <Stack direction="row" spacing={1} alignItems="center"
          sx={fullPage ? { maxWidth: 820, mx: 'auto', width: '100%' } : undefined}>
          <AutoAwesomeOutlinedIcon fontSize="small" color="secondary" />
          <Box sx={{ minWidth: 0, flex: 1 }}>
            <Typography variant="subtitle1" fontWeight={750}>Planner assistant</Typography>
            <Typography variant="caption" color="text.secondary">
              {plan?.plan_id ? 'Read-only plan review' : 'Describe the plan you want to prepare'}
            </Typography>
          </Box>
          <Stack direction="row" spacing={0.5} alignItems="center">
            <Tooltip title="Previous chat sessions">
              <Box component="span" sx={{ display: 'inline-flex' }}>
                <IconButton aria-label="Previous chat sessions" size="small"
                  onClick={(event) => setSessionsAnchor(event.currentTarget)}>
                  <HistoryOutlinedIcon fontSize="small" />
                </IconButton>
              </Box>
            </Tooltip>
            <Menu anchorEl={sessionsAnchor} open={Boolean(sessionsAnchor)} onClose={() => setSessionsAnchor(null)}
              anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
              transformOrigin={{ vertical: 'top', horizontal: 'right' }}
              slotProps={{ paper: { sx: { width: 300, maxWidth: '90vw' } } }}>
              {pastSessions.length === 0 ? (
                <MenuItem disabled>No previous sessions yet</MenuItem>
              ) : pastSessions.map((session) => (
                <MenuItem key={session.id} onClick={() => openPastSession(session)}
                  sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                  <Box sx={{ minWidth: 0, flex: 1 }}>
                    <Typography variant="body2" noWrap>{session.title}</Typography>
                    <Typography variant="caption" color="text.secondary">
                      {new Date(session.savedAt).toLocaleString()}
                    </Typography>
                  </Box>
                  <IconButton size="small" aria-label="Delete session"
                    onClick={(event) => { event.stopPropagation(); deletePastSession(session.id) }}>
                    <DeleteOutlineIcon fontSize="small" />
                  </IconButton>
                </MenuItem>
              ))}
            </Menu>
            <Tooltip title="Clear chat">
              <Box component="span" sx={{ display: 'inline-flex' }}>
                <IconButton aria-label="Clear chat" size="small" onClick={clearChat}
                  disabled={sending || (!messages.length && !error && !input)}>
                  <ClearAllOutlinedIcon fontSize="small" />
                </IconButton>
              </Box>
            </Tooltip>
            <Tooltip title={fullPage ? 'Return to side chat' : 'Expand chat to full page'}>
              <Box component="span" sx={{ display: 'inline-flex' }}>
                <IconButton aria-label={fullPage ? 'Return to side chat' : 'Expand chat to full page'} size="small"
                  onClick={() => setFullPage((current) => !current)}>
                  {fullPage
                    ? <CloseFullscreenOutlinedIcon fontSize="small" />
                    : <OpenInFullOutlinedIcon fontSize="small" />}
                </IconButton>
              </Box>
            </Tooltip>
          </Stack>
        </Stack>
      </Box>

      <Divider />
      <Box sx={{ flex: 1, minHeight: 0, overflowY: 'auto', px: 1.5, py: 1.5 }}>
        <Box sx={fullPage ? { maxWidth: 820, mx: 'auto' } : undefined}>
        {messages.length === 0 && (
          <Box sx={{ px: 0.5, py: 1 }}>
            <Typography variant="body2" color="text.secondary">
              {plan?.plan_id
                ? 'Ask about the plan, its checks, or a specific order.'
                : 'Ask in plain language. I will stage the requested form changes for you to review.'}
            </Typography>
          </Box>
        )}
        <Stack spacing={1.25}>
          {messages.map((item) => (
            <Box key={item.id} sx={{
              alignSelf: item.role === 'user' ? 'flex-end' : 'stretch',
              maxWidth: item.role === 'user' ? '92%' : '100%',
            }}>
              <Box sx={{
                px: 1.25, py: 1, borderRadius: 1,
                bgcolor: item.role === 'user' ? 'action.selected' : 'background.default',
                border: 1, borderColor: 'divider',
              }}>
                {item.role === 'assistant' ? (
                  <Box sx={{ overflowWrap: 'anywhere',
                    '& p': { my: 0, mb: 1 }, '& p:last-child': { mb: 0 },
                    '& ul, & ol': { pl: 2.5, my: 0.75 }, '& li': { mb: 0.4 },
                    '& h1, & h2, & h3, & h4': { fontSize: '0.95rem', fontWeight: 700, mt: 1.25, mb: 0.5 },
                    '& strong': { fontWeight: 700 },
                    '& code': { px: 0.4, borderRadius: 0.5, bgcolor: 'action.hover', overflowWrap: 'anywhere' },
                  }}>
                    <ReactMarkdown remarkPlugins={[remarkGfm]} components={{
                      table: ({ children }) => (
                        <Box sx={{ overflowX: 'auto', my: 1, maxWidth: '100%' }}>
                          <Box component="table" sx={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.85rem',
                            '& th, & td': { border: 1, borderColor: 'divider', px: 0.75, py: 0.5, textAlign: 'left' },
                            '& th': { bgcolor: 'action.hover', fontWeight: 700 },
                          }}>{children}</Box>
                        </Box>
                      ),
                    }}>{item.content}</ReactMarkdown>
                  </Box>
                ) : (
                  <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>
                    {item.content}
                  </Typography>
                )}
                {item.updates && Object.keys(item.updates).length > 0 && (
                  <Stack direction="row" spacing={0.5} sx={{ mt: 1, flexWrap: 'wrap', gap: 0.5 }}>
                    {Object.entries(item.updates).map(([key, value]) => (
                      <Chip key={key} size="small" variant="outlined"
                        label={`${FIELD_LABELS[key] || key}: ${displayValue(key, value, funds)}`} />
                    ))}
                  </Stack>
                )}
                {item.readyToGenerate && !plan?.plan_id && (
                  <Button size="small" variant="contained" sx={{ mt: 1 }}
                    disabled={busy || generating}
                    onClick={() => setConfirmation({ text: item.requestedText })}>
                    Confirm &amp; Generate Plan
                  </Button>
                )}
                {item.toolsUsed?.length > 0 && (
                  <Typography variant="caption" display="block" color="text.secondary" sx={{ mt: 0.5 }}>
                    Checked: {[...new Set(item.toolsUsed)].map((tool) => tool.replaceAll('_', ' ')).join(', ')}
                  </Typography>
                )}
              </Box>
            </Box>
          ))}
          {sending && (
            <Stack direction="row" spacing={1} alignItems="center" sx={{ px: 1 }}>
              <CircularProgress size={15} />
              <Typography variant="caption" color="text.secondary">
                {plan?.plan_id ? 'Checking the plan…' : 'Interpreting and staging changes…'}
              </Typography>
            </Stack>
          )}
          <div ref={endRef} />
        </Stack>
        </Box>
      </Box>

      {error && (
        <Box sx={fullPage ? { maxWidth: 820, mx: 'auto', width: '100%' } : undefined}>
          <Alert severity="error" sx={{ mx: 1.5, mb: 1 }}>{error}</Alert>
        </Box>
      )}

      <Box sx={{ px: 1.5, pb: 1 }}>
        <Box sx={fullPage ? { maxWidth: 820, mx: 'auto' } : undefined}>
        <Box sx={{ mb: 1, minHeight: 36 }}>
          {displayedPrompts.length > 0 && (
            <Stack direction="row" alignItems="flex-start" sx={{ flexWrap: 'wrap', gap: 0.75 }}>
              {displayedPrompts.map((prompt) => (
                <Chip key={prompt} size="small" label={prompt} variant="outlined"
                  sx={{ height: 'auto', maxWidth: '100%',
                    '& .MuiChip-label': { display: 'block', whiteSpace: 'normal', py: 0.65, lineHeight: 1.3, textAlign: 'left' } }}
                  disabled={sending || busy} onClick={() => submit(prompt)} />
              ))}
            </Stack>
          )}
        </Box>
        <Stack direction="row" alignItems="flex-end" spacing={0.75}>
          <TextField fullWidth multiline maxRows={4} size="small"
            placeholder={plan?.plan_id ? 'Ask about this plan' : 'Describe an intent or ask for a plan'}
            value={input} disabled={sending || busy}
            onChange={(event) => setInput(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault()
                submit()
              }
            }} />
          <Tooltip title="Send">
            <span>
              <IconButton aria-label="Send message" color="primary" onClick={() => submit()}
                disabled={!input.trim() || sending || busy}>
                <SendOutlinedIcon />
              </IconButton>
            </span>
          </Tooltip>
        </Stack>
        </Box>
      </Box>

      <Dialog open={Boolean(confirmation)} onClose={() => setConfirmation(null)} maxWidth="xs" fullWidth>
        <DialogTitle>Generate this trade plan?</DialogTitle>
        <DialogContent>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
            Review the staged values before sending the request to the deterministic planner.
          </Typography>
          <Stack spacing={0.75}>
            <Typography variant="body2"><strong>Fund:</strong> {draft.fund_name || fundId}</Typography>
            <Typography variant="body2"><strong>Action:</strong> {draft.action}</Typography>
            {draft.amount_cr != null && <Typography variant="body2"><strong>Amount:</strong> ₹{draft.amount_cr} Cr</Typography>}
            {draft.targets?.length > 0 && <Typography variant="body2"><strong>Targets:</strong> {draft.targets.join(', ')}</Typography>}
            {draft.manual_selections?.length > 0 && (
              <Typography variant="body2"><strong>Manual securities:</strong> {displayValue('manual_selections', draft.manual_selections, funds)}</Typography>
            )}
            {draft.manual_sector_selections?.length > 0 && (
              <Typography variant="body2"><strong>Manual sectors:</strong> {displayValue('manual_sector_selections', draft.manual_sector_selections, funds)}</Typography>
            )}
            <Typography variant="body2"><strong>Approach:</strong> {draft.method}</Typography>
            <Typography variant="body2"><strong>Horizon:</strong> {draft.horizon_days} days</Typography>
            <Typography variant="body2"><strong>Dates:</strong> {draft.trade_date} to {draft.settlement_date}</Typography>
            {draft.target_volatility != null && (
              <Typography variant="body2"><strong>Risk target:</strong> {displayValue('target_volatility', draft.target_volatility, funds)}</Typography>
            )}
            <Typography variant="body2"><strong>Request:</strong> {confirmation?.text}</Typography>
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setConfirmation(null)}>Review first</Button>
          <Button variant="contained" onClick={confirmGenerate} disabled={generating || busy}>
            {generating ? 'Generating…' : 'Confirm & Generate'}
          </Button>
        </DialogActions>
      </Dialog>
    </Paper>
  )
}