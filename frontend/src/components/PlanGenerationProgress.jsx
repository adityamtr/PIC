import { Box, CircularProgress, LinearProgress, Stack, Typography } from '@mui/material'
import AccountBalanceWalletOutlinedIcon from '@mui/icons-material/AccountBalanceWalletOutlined'
import AutoGraphOutlinedIcon from '@mui/icons-material/AutoGraphOutlined'
import CheckIcon from '@mui/icons-material/Check'
import FactCheckOutlinedIcon from '@mui/icons-material/FactCheckOutlined'
import ShieldOutlinedIcon from '@mui/icons-material/ShieldOutlined'
import { Panel } from './ui'

const STAGES = [
  {
    title: 'Validating portfolio manager intent',
    detail: 'Confirming the action, dates, allocation method, and requested amount.',
    icon: FactCheckOutlinedIcon,
  },
  {
    title: 'Reviewing available cash flow',
    detail: 'Factoring in investable cash, commitments, and unsettled trades.',
    icon: AccountBalanceWalletOutlinedIcon,
  },
  {
    title: 'Constructing the trade allocation',
    detail: 'Building a rules-based, manual, or optimized order set.',
    icon: AutoGraphOutlinedIcon,
  },
  {
    title: 'Running compliance and risk checks',
    detail: 'Testing concentration, liquidity, timing, tax, and execution constraints.',
    icon: ShieldOutlinedIcon,
  },
  {
    title: 'Preparing the PIC review package',
    detail: 'Assembling the recommendation, orders, and decision-ready findings.',
    icon: FactCheckOutlinedIcon,
  },
]

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
  return (
    <CircularProgress size={20} thickness={5} sx={{ color: 'inherit' }} />
  )
}

export default function PlanGenerationProgress({ elapsedSeconds }) {
  const progress = Math.min(100, Math.round((elapsedSeconds / 15) * 100))
  const activeStageIndex = Math.min(STAGES.length - 1, Math.floor(elapsedSeconds / 3))

  return (
    <Panel highlight bodySx={{ py: 3 }}>
      <Box aria-live="polite" aria-busy="true">
        <Box>
          <Typography variant="overline" color="primary" sx={{ fontWeight: 800, letterSpacing: 0.8 }}>
            Plan generation in progress
          </Typography>
          <Typography variant="subtitle1" sx={{ fontWeight: 700, mt: 0.25 }}>
            Building a decision-ready trade plan
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
            The planning agent is working through the controls behind your recommendation.
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
            const completeAt = (index + 1) * 3
            const complete = elapsedSeconds >= completeAt
            const active = !complete && index === activeStageIndex
            const Icon = stage.icon

            return (
              <Stack key={stage.title} direction="row" spacing={1.5} alignItems="flex-start"
                sx={{ py: 1.25, opacity: complete || active ? 1 : 0.42 }}>
                <Box sx={{ width: 30, height: 30, borderRadius: '50%', display: 'grid', placeItems: 'center', flexShrink: 0,
                  bgcolor: complete ? 'primary.main' : active ? 'action.selected' : 'action.hover',
                  color: complete ? 'primary.contrastText' : active ? 'primary.main' : 'text.secondary',
                  border: 1, borderColor: complete || active ? 'primary.main' : 'divider' }}>
                  {complete ? <CompletedStageIcon /> : active ? <ActiveStageIcon /> : <Icon fontSize="small" />}
                </Box>
                <Box sx={{ minWidth: 0, pt: 0.25 }}>
                  <Typography variant="body2" fontWeight={active ? 800 : 700}>{stage.title}</Typography>
                  <Typography variant="caption" color="text.secondary">{stage.detail}</Typography>
                </Box>
              </Stack>
            )
          })}
        </Stack>
      </Box>
    </Panel>
  )
}
