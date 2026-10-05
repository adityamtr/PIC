import { useEffect, useMemo, useState } from 'react'
import {
  Alert, AppBar, Box, Chip, CircularProgress, Container, CssBaseline, Fade, IconButton, MenuItem, Select,
  Snackbar, Tab, Tabs, ThemeProvider, Toolbar, Tooltip, Typography,
} from '@mui/material'
import DarkModeIcon from '@mui/icons-material/DarkModeOutlined'
import LightModeIcon from '@mui/icons-material/LightModeOutlined'
import RestartAltIcon from '@mui/icons-material/RestartAlt'
import CandlestickChartOutlinedIcon from '@mui/icons-material/CandlestickChartOutlined'
import AccountBalanceWalletOutlinedIcon from '@mui/icons-material/AccountBalanceWalletOutlined'
import SwapHorizOutlinedIcon from '@mui/icons-material/SwapHorizOutlined'
import HistoryOutlinedIcon from '@mui/icons-material/HistoryOutlined'
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
  const [funds, setFunds] = useState([])
  const [fundId, setFundId] = useState('')
  const [resetting, setResetting] = useState(false)
  const [resetError, setResetError] = useState('')

  const theme = useMemo(() => buildTheme(mode), [mode])

  useEffect(() => { localStorage.setItem('pic-mode', mode) }, [mode])
  useEffect(() => {
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
        <Toolbar sx={{ gap: 1.25, flexWrap: { xs: 'wrap', sm: 'nowrap' },
          py: { xs: 1, sm: 0 }, minHeight: { xs: 'auto', sm: 64 } }}>
          <Logo size={38} mode={mode} />
          <Box sx={{ lineHeight: 1.1 }}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75 }}>
              <Typography variant="h6" sx={{ fontWeight: 800, letterSpacing: 0.2, lineHeight: 1.2,
                background: BRAND_GRADIENT, WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' }}>
                PIC Tool
              </Typography>
              <Chip label="PRO" size="small" variant="outlined" sx={{
                height: 18,
                borderRadius: 1,
                fontSize: '0.6rem',
                fontWeight: 800,
                letterSpacing: 0.5,
                color: mode === 'dark' ? '#5A9DB7' : '#087F70',
                borderColor: mode === 'dark' ? 'rgba(90,157,183,0.45)' : 'rgba(8,127,112,0.28)',
                bgcolor: mode === 'dark' ? 'rgba(49,126,158,0.12)' : 'rgba(8,127,112,0.05)',
                '& .MuiChip-label': { px: 0.75 },
              }} />
            </Box>
            <Typography variant="caption" color="text.secondary"
              sx={{ display: { xs: 'none', sm: 'block' }, letterSpacing: 0.6, textTransform: 'uppercase', fontWeight: 600 }}>
              Trade-Plan Workbench
            </Typography>
          </Box>
          <Box sx={{ flexGrow: { xs: 0, sm: 1 }, width: { xs: 0, sm: 'auto' } }} />
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, minWidth: 0,
            width: { xs: '100%', sm: 'auto' }, flex: { sm: '0 0 auto' } }}>
            {funds.length > 0 && (
              <Select size="small" value={fundId} onChange={(e) => {
                setFundId(e.target.value)
                setFocusedPlanId('')
              }}
                sx={{ minWidth: { xs: 112, sm: 220 }, flex: { xs: '1 1 120px', sm: '0 0 auto' },
                  maxWidth: { xs: 'none', sm: 'none' }, fontWeight: 600 }}>
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
          </Box>
        </Toolbar>
        <Tabs value={tab} onChange={(_, v) => setTab(v)} variant="scrollable"
          scrollButtons="auto" allowScrollButtonsMobile sx={{ px: { xs: 0.5, sm: 2 }, minHeight: 48,
            '& .MuiTab-root': { minHeight: 48, py: 0.5, px: { xs: 1, sm: 1.5 } } }}
          textColor="primary" indicatorColor="primary">
          <Tab icon={<CandlestickChartOutlinedIcon />} iconPosition="start" label="Trade Planner" />
          <Tab icon={<AccountBalanceWalletOutlinedIcon />} iconPosition="start" label="Portfolio" />
          <Tab icon={<SwapHorizOutlinedIcon />} iconPosition="start" label="Trades" />
          <Tab icon={<HistoryOutlinedIcon />} iconPosition="start" label="Plan History" />
        </Tabs>
      </AppBar>

      <Container maxWidth={false} sx={{ py: 3, px: { xs: 1.5, sm: 2.5, xl: 4 } }}>
        {fundId && (
          <>
            {/* Trade Planner stays mounted (hidden via display:none rather than
                unmounted) so a generated plan survives switching tabs and coming
                back. The other tabs keep remounting per visit, since they rely
                on that to refetch fresh data. */}
            <Box sx={{ display: tab === 0 ? 'block' : 'none' }}>
              <TradePlanner fundId={fundId} funds={funds} onChangeFundId={setFundId}
                onContinueToEmail={continueToEmail} />
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
