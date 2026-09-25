import { useEffect, useMemo, useState } from 'react'
import {
  AppBar, Box, Chip, Container, CssBaseline, Fade, IconButton, MenuItem, Select,
  Tab, Tabs, ThemeProvider, Toolbar, Tooltip, Typography,
} from '@mui/material'
import DarkModeIcon from '@mui/icons-material/DarkModeOutlined'
import LightModeIcon from '@mui/icons-material/LightModeOutlined'
import CircleIcon from '@mui/icons-material/Circle'
import { buildTheme, BRAND_GRADIENT } from './theme'
import { Logo } from './components/Logo'
import { api } from './api'
import TradePlanner from './components/TradePlanner'
import Portfolio from './components/Portfolio'
import Trades from './components/Trades'

export default function App() {
  const [mode, setMode] = useState(() => localStorage.getItem('pic-mode') || 'light')
  const [tab, setTab] = useState(0)
  const [apiUp, setApiUp] = useState(null)
  const [funds, setFunds] = useState([])
  const [fundId, setFundId] = useState('')

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
            <Select size="small" value={fundId} onChange={(e) => setFundId(e.target.value)}
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
        </Toolbar>
        <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ px: 2 }}
          textColor="primary" indicatorColor="primary">
          <Tab label="Trade Planner" />
          <Tab label="Portfolio" />
          <Tab label="Trades" />
        </Tabs>
      </AppBar>

      <Container maxWidth="lg" sx={{ py: 3 }}>
        {fundId && (
          <Fade in key={`${tab}-${fundId}`} timeout={350}>
            <Box>
              {tab === 0 && <TradePlanner fundId={fundId} />}
              {tab === 1 && <Portfolio fundId={fundId} />}
              {tab === 2 && <Trades fundId={fundId} />}
            </Box>
          </Fade>
        )}
        <Typography variant="caption" color="text.secondary"
          sx={{ display: 'block', textAlign: 'center', mt: 5 }}>
          Synthetic data for demonstration only · Illustrative fund data · Not investment advice
        </Typography>
      </Container>
    </ThemeProvider>
  )
}
