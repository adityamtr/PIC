import { useEffect, useState } from 'react'
import {
  Accordion, AccordionDetails, AccordionSummary, Box, CircularProgress, Fade, LinearProgress, Stack, Typography,
} from '@mui/material'
import AccountBalanceWalletOutlinedIcon from '@mui/icons-material/AccountBalanceWalletOutlined'
import AutoGraphOutlinedIcon from '@mui/icons-material/AutoGraphOutlined'
import CheckIcon from '@mui/icons-material/Check'
import CheckCircleIcon from '@mui/icons-material/CheckCircle'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import FactCheckOutlinedIcon from '@mui/icons-material/FactCheckOutlined'
import ShieldOutlinedIcon from '@mui/icons-material/ShieldOutlined'
import { Panel } from './ui'

// Stage metadata, keyed by the backend `phase` id emitted over SSE. Each phase
// streams several granular steps (real order counts, investable cash, tax drag,
// compliance tallies); these titles/icons are just the frame around them.
const STAGES = [
  { phase: 'intent', title: 'Validating portfolio manager intent', icon: FactCheckOutlinedIcon },
  { phase: 'cash_flow', title: 'Reviewing available cash flow', icon: AccountBalanceWalletOutlinedIcon },
  { phase: 'allocation', title: 'Constructing the trade allocation', icon: AutoGraphOutlinedIcon },
  { phase: 'compliance_risk', title: 'Running compliance and risk checks', icon: ShieldOutlinedIcon },
  { phase: 'package', title: 'Preparing the PIC review package', icon: FactCheckOutlinedIcon },
]

// Professional rotating verbs for the global generating indicator.
const STATUS_WORDS = ['Analyzing', 'Computing', 'Optimizing', 'Reconciling', 'Evaluating', 'Synthesizing', 'Finalizing']

function CompletedStageIcon() {
  return (
    <Box sx={{ position: 'relative', width: 20, height: 20, display: 'grid', placeItems: 'center' }}>
      <CircularProgress variant="determinate" value={100} size={20} thickness={5}
        sx={{ position: 'absolute', color: 'inherit' }} />
      <CheckIcon sx={{ position: 'relative', fontSize: 13 }} />
    </Box>
  )
}

function ActiveStageIcon() {
  return <CircularProgress size={20} thickness={5} sx={{ color: 'inherit' }} />
}

function RotatingStatusWord() {
  const [i, setI] = useState(0)
  useEffect(() => {
    const t = window.setInterval(() => setI((prev) => (prev + 1) % STATUS_WORDS.length), 1400)
    return () => window.clearInterval(t)
  }, [])
  return (
    <Fade key={STATUS_WORDS[i]} in timeout={400}>
      <Typography component="span" variant="overline"
        sx={{ fontWeight: 800, letterSpacing: 0.8, color: 'primary.main' }}>
        {STATUS_WORDS[i]}…
      </Typography>
    </Fade>
  )
}

// One granular step line (label + its real output detail).
function StepLine({ label, detail }) {
  return (
    <Fade in timeout={350}>
      <Box sx={{ mt: 0.5 }}>
        <Typography variant="caption" sx={{ display: 'block', fontWeight: 700, lineHeight: 1.4 }}>
          {label}
        </Typography>
        {detail ? (
          <Typography variant="caption" color="text.secondary"
            sx={{ display: 'block', lineHeight: 1.4, fontVariantNumeric: 'tabular-nums' }}>
            {detail}
          </Typography>
        ) : null}
      </Box>
    </Fade>
  )
}

// `events` is the list of real granular progress events received so far, each
// shaped { phase, index, total, step, label, detail, data }. `done` flips once
// the plan has actually arrived, so the bar can finish at 100% with every
// stage ticked instead of freezing at the last stage's "active" state.
export default function PlanGenerationProgress({ events = [], done = false }) {
  const total = events[0]?.total || STAGES.length
  const activePhaseIndex = done ? total : (events.length ? events[events.length - 1].index : 0)
  const progress = done ? 100 : Math.round((activePhaseIndex / total) * 100)

  const stepsByPhase = new Map()
  for (const e of events) {
    if (!stepsByPhase.has(e.phase)) stepsByPhase.set(e.phase, [])
    stepsByPhase.get(e.phase).push(e)
  }

  return (
    <Panel highlight bodySx={{ py: 3 }}>
      <Box aria-live="polite" aria-busy={!done}>
        <Box>
          <Stack direction="row" alignItems="center" spacing={1}>
            {done
              ? <Fade in timeout={300}><CheckCircleIcon sx={{ fontSize: 18, color: 'success.main' }} /></Fade>
              : <CircularProgress size={16} thickness={5} />}
            {done
              ? <Typography component="span" variant="overline"
                  sx={{ fontWeight: 800, letterSpacing: 0.8, color: 'success.main' }}>
                  Done…
                </Typography>
              : <RotatingStatusWord />}
          </Stack>
          <Typography variant="subtitle1" sx={{ fontWeight: 700, mt: 0.25 }}>
            {done ? 'Plan is ready' : 'Building a decision-ready trade plan'}
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
            {done
              ? 'All checks passed. Opening the plan for review…'
              : 'The planning agent is working through the controls behind your recommendation.'}
          </Typography>
        </Box>

        <Stack direction="row" alignItems="center" spacing={1} sx={{ mt: 2.5, mb: 0.75 }}>
          <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 700 }}>
            Progress
          </Typography>
          <Typography variant="caption" color="text.secondary"
            sx={{ fontWeight: 700, fontVariantNumeric: 'tabular-nums' }}>
            {progress}%
          </Typography>
        </Stack>
        <LinearProgress
          variant="determinate"
          value={progress}
          aria-label="Trade plan generation progress"
          sx={{ height: 7, borderRadius: 1, bgcolor: 'action.hover' }}
        />

        <Stack spacing={0} sx={{ mt: 2.5 }}>
          {STAGES.map((stage, index) => {
            const steps = stepsByPhase.get(stage.phase) || []
            const complete = index < activePhaseIndex
            const active = index === activePhaseIndex
            const Icon = stage.icon

            return (
              <Stack key={stage.phase} direction="row" spacing={1.5} alignItems="flex-start"
                sx={{ py: 1.25, opacity: complete || active ? 1 : 0.42 }}>
                <Box sx={{ width: 30, height: 30, borderRadius: '50%', display: 'grid', placeItems: 'center', flexShrink: 0,
                  bgcolor: complete ? 'primary.main' : active ? 'action.selected' : 'action.hover',
                  color: complete ? 'primary.contrastText' : active ? 'primary.main' : 'text.secondary',
                  border: 1, borderColor: complete || active ? 'primary.main' : 'divider' }}>
                  {complete ? <CompletedStageIcon /> : active ? <ActiveStageIcon /> : <Icon fontSize="small" />}
                </Box>
                <Box sx={{ minWidth: 0, pt: 0.25, flex: 1 }}>
                  <Typography variant="body2" fontWeight={active ? 800 : 700}>{stage.title}</Typography>
                  {steps.map((s) => <StepLine key={s.step} label={s.label} detail={s.detail} />)}
                  {active && steps.length === 0 ? (
                    <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5 }}>
                      Working…
                    </Typography>
                  ) : null}
                </Box>
              </Stack>
            )
          })}
        </Stack>
      </Box>
    </Panel>
  )
}

// Read-only recap of the same granular steps, shown collapsed inside the
// finished plan so the user can see exactly which checks/rules ran without
// re-triggering generation. `events` is the same array PlanGenerationProgress
// was fed while loading.
export function GenerationStepsSummary({ events = [] }) {
  if (!events.length) return null

  const stepsByPhase = new Map()
  for (const e of events) {
    if (!stepsByPhase.has(e.phase)) stepsByPhase.set(e.phase, [])
    stepsByPhase.get(e.phase).push(e)
  }
  const stepCount = events.filter((e) => e.step).length

  return (
    <Panel icon={<FactCheckOutlinedIcon />} title="How this plan was generated" bodySx={{ pb: 0 }}>
      <Accordion disableGutters elevation={0} sx={{
        bgcolor: 'transparent', mt: -1,
        '&:before': { display: 'none' },
      }}>
        <AccordionSummary expandIcon={<ExpandMoreIcon />} sx={{ px: 0, minHeight: 40,
          '& .MuiAccordionSummary-content': { my: 1 } }}>
          <Typography variant="body2" color="text.secondary">
            {stepCount} check{stepCount === 1 ? '' : 's'} across {STAGES.length} stages — view the detail
          </Typography>
        </AccordionSummary>
        <AccordionDetails sx={{ px: 0, pt: 0, pb: 1.5 }}>
          <Stack spacing={0}>
            {STAGES.map((stage) => {
              const steps = stepsByPhase.get(stage.phase) || []
              if (!steps.length) return null
              const Icon = stage.icon
              return (
                <Stack key={stage.phase} direction="row" spacing={1.5} alignItems="flex-start" sx={{ py: 1.25 }}>
                  <Box sx={{ width: 28, height: 28, borderRadius: '50%', display: 'grid', placeItems: 'center',
                    flexShrink: 0, bgcolor: 'action.selected', color: 'primary.main', border: 1, borderColor: 'primary.main' }}>
                    <Icon fontSize="small" />
                  </Box>
                  <Box sx={{ minWidth: 0, pt: 0.25, flex: 1 }}>
                    <Typography variant="body2" fontWeight={700}>{stage.title}</Typography>
                    {steps.map((s) => <StepLine key={s.step} label={s.label} detail={s.detail} />)}
                  </Box>
                </Stack>
              )
            })}
          </Stack>
        </AccordionDetails>
      </Accordion>
    </Panel>
  )
}
