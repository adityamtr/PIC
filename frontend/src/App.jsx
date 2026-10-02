import { useEffect, useMemo, useState } from 'react'
import {
  Alert, AppBar, Box, Chip, CircularProgress, Container, CssBaseline, Fade, IconButton, MenuItem, Select,
  Snackbar, Tab, Tabs, ThemeProvider, Toolbar, Tooltip, Typography,
} from '@mui/material'
import DarkModeIcon from '@mui/icons-material/DarkModeOutlined'
import LightModeIcon from '@mui/icons-material/LightModeOutlined'
import RestartAltIcon from '@mui/icons-material/RestartAlt'
import CircleIcon from '@mui/icons-material/Circle'
import { buildTheme, BRAND_GRADIENT } from './theme'
import { Logo } from './components/Logo'
import { api } from './api'
import TradePlanner from './components/TradePlanner'
import Portfolio from './components/Portfolio'
import Trades from './components/Trades'
import PlanHistory from './components/PlanHistory'

export default function App() {
  const [mode, setMode] = useState(() => localStorage.getItem('pic-mode') || 'light')
  const [tab, setTab] = useState(0)
  const [focusedPlanId, setFocusedPlanId] = useState('')
  const [apiUp, setApiUp] = useState(null)
  const [funds, setFunds] = useState([])
  const [fundId, setFundId] = useState('')
  const [resetting, setResetting] = useState(false)
  const [resetError, setResetError] = useState('')

  const theme = useMemo(() => buildTheme(mode), [mode])

  useEffect(() => { localStorage.setItem('pic-mode', mode) }, [mode])
  useEffect(() => {
    api.health().then(() => setApiUp(true)).catch(() => setApiUp(false))
    api.funds().then((d) => {
      setFunds(d.funds)
      setFundId((current) => current || d.default)
    }).catch(() => {})
  }, [])

  const toggleMode = () => setMode((m) => (m === 'light' ? 'dark' : 'light'))

  function continueToEmail(planId) {
    setFocusedPlanId(planId)
    setTab(3)
  }

  async function handleResetDb() {
    if (!window.confirm('Reset the database to its freshly-seeded state? '
      + 'This permanently deletes every generated plan and decision.')) return
    setResetting(true); setResetError('')
    try {
      await api.resetDb()
      window.location.reload()
    } catch (e) {
      setResetError(e.message)
      setResetting(false)
    }
  }

  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <AppBar position="sticky" color="default" elevation={0}
        sx={{ borderBottom: 1, borderColor: 'divider', bgcolor: 'background.paper' }}>
        <Toolbar sx={{ gap: 1.5 }}>
          <Logo size={34} />
          <Typography variant="h6" sx={{ fontWeight: 800,
            background: BRAND_GRADIENT, WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' }}>
            WealthVector
          </Typography>
          <Chip size="small" label="PIC middle layer" variant="outlined" color="primary"
            sx={{ display: { xs: 'none', sm: 'inline-flex' } }} />
          <Box sx={{ flexGrow: 1 }} />
          {funds.length > 0 && (
            <Select size="small" value={fundId} onChange={(e) => {
              setFundId(e.target.value)
              setFocusedPlanId('')
            }}
              sx={{ minWidth: 220, fontWeight: 600 }}>
              {funds.map((f) => (
                <MenuItem key={f.fund_id} value={f.fund_id}>
                  {f.name}
                  <Typography component="span" variant="caption" color="text.secondary" sx={{ ml: 1 }}>
                    {f.category?.replace('Equity - ', '')}
                  </Typography>
                </MenuItem>
              ))}
            </Select>
          )}
          <Chip size="small" variant="outlined"
            icon={<CircleIcon sx={{ fontSize: '0.7rem !important',
              color: apiUp === true ? 'success.main' : apiUp === false ? 'error.main' : 'text.disabled' }} />}
            label={apiUp === true ? 'API' : apiUp === false ? 'Offline' : '…'} />
          <Tooltip title={mode === 'light' ? 'Dark mode' : 'Light mode'}>
            <IconButton onClick={toggleMode} color="inherit">
              {mode === 'light' ? <DarkModeIcon /> : <LightModeIcon />}
            </IconButton>
          </Tooltip>
          <Tooltip title="Reset database (reseed from source data)">
            <span>
              <IconButton onClick={handleResetDb} color="inherit" disabled={resetting}>
                {resetting ? <CircularProgress size={20} color="inherit" /> : <RestartAltIcon />}
              </IconButton>
            </span>
          </Tooltip>
        </Toolbar>
        <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ px: 2 }}
          textColor="primary" indicatorColor="primary">
          <Tab label="Trade Planner" />
          <Tab label="Portfolio" />
          <Tab label="Trades" />
          <Tab label="Plan History" />
        </Tabs>
      </AppBar>

      <Container maxWidth="lg" sx={{ py: 3 }}>
        {fundId && (
          <>
            {/* Trade Planner stays mounted (hidden via display:none rather than
                unmounted) so a generated plan survives switching tabs and coming
                back. The other tabs keep remounting per visit, since they rely
                on that to refetch fresh data. */}
            <Box sx={{ display: tab === 0 ? 'block' : 'none' }}>
              <TradePlanner fundId={fundId} onContinueToEmail={continueToEmail} />
            </Box>
            {tab !== 0 && (
              <Fade in key={`${tab}-${fundId}`} timeout={350}>
                <Box>
                  {tab === 1 && <Portfolio fundId={fundId} />}
                  {tab === 2 && <Trades fundId={fundId} />}
                  {tab === 3 && <PlanHistory fundId={fundId} focusPlanId={focusedPlanId} />}
                </Box>
              </Fade>
            )}
          </>
        )}
        <Typography variant="caption" color="text.secondary"
          sx={{ display: 'block', textAlign: 'center', mt: 5 }}>
          Synthetic data for demonstration only · Illustrative fund data · Not investment advice
        </Typography>
      </Container>
      <Snackbar open={Boolean(resetError)} autoHideDuration={6000} onClose={() => setResetError('')}>
        <Alert severity="error" variant="filled" onClose={() => setResetError('')}>
          Database reset failed: {resetError}
        </Alert>
      </Snackbar>
    </ThemeProvider>
  )
}
