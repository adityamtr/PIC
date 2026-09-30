import { Box, CircularProgress, Fade, LinearProgress, Stack, Typography } from '@mui/material'
import AccountBalanceWalletOutlinedIcon from '@mui/icons-material/AccountBalanceWalletOutlined'
import AutoGraphOutlinedIcon from '@mui/icons-material/AutoGraphOutlined'
import CheckIcon from '@mui/icons-material/Check'
import FactCheckOutlinedIcon from '@mui/icons-material/FactCheckOutlined'
import ShieldOutlinedIcon from '@mui/icons-material/ShieldOutlined'
import { Panel } from './ui'

const STAGES = [
  {
    title: 'Validating portfolio manager intent',
    steps: [
      'Parsing the action, amount, target sectors, and allocation method.',
      'Resolving selected sector names against the supported universe.',
      'Checking the amount and trade-to-settlement horizon.',
    ],
    icon: FactCheckOutlinedIcon,
  },
  {
    title: 'Reviewing available cash flow',
    steps: [
      'Loading fund cash, reserve buffer, and unsettled trade impact.',
      'Adding expected dividends and net subscription or redemption flows.',
      'Deducting accrued expenses to calculate investable cash.',
    ],
    icon: AccountBalanceWalletOutlinedIcon,
  },
  {
    title: 'Constructing the trade allocation',
    steps: [
      'Generating one-month return forecasts for holdings and the universe.',
      'Running the manual, rules-based, or convex-optimization allocation path.',
      'Sizing share-level orders and assigning eligible NSE/BSE trade dates.',
    ],
    icon: AutoGraphOutlinedIcon,
  },
  {
    title: 'Running compliance and risk checks',
    steps: [
      'Calculating sell-side tax lots and tax drag.',
      'Reprojecting issuer, sector, and group concentration after trades.',
      'Evaluating liquidity, lock-ins, events, and policy controls.',
    ],
    icon: ShieldOutlinedIcon,
  },
  {
    title: 'Preparing the PIC review package',
    steps: [
      'Compiling cash impact, orders, compliance results, and risk flags.',
      'Selecting the recommendation from pass, warn, block, or escalation outcomes.',
      'Creating the plan in Pending PIC Review for human decision.',
    ],
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
            const visibleStepCount = complete
              ? stage.steps.length
              : active ? Math.min(stage.steps.length, elapsedSeconds - index * 3 + 1) : 0

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
                  <Stack spacing={0.35} sx={{ mt: 0.5 }}>
                    {stage.steps.slice(0, visibleStepCount).map((step) => (
                      <Fade key={step} in timeout={350}>
                        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', lineHeight: 1.45 }}>
                          {step}
                        </Typography>
                      </Fade>
                    ))}
                  </Stack>
                </Box>
              </Stack>
            )
          })}
        </Stack>
      </Box>
    </Panel>
  )
}
