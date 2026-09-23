import { useEffect, useState } from 'react'
import {
  Alert, Box, Chip, CircularProgress, LinearProgress, Stack, Table, TableBody,
  TableCell, TableHead, TableRow, Typography,
} from '@mui/material'
import LockIcon from '@mui/icons-material/LockOutlined'
import { api } from '../api'
import { fmtCrValue, fmtPct, fmtRupee } from '../format'
import { KpiGrid, Panel, ScrollX, Stat } from './ui'
import SectorDonut from './SectorDonut'

function Meter({ used, limit, status }) {
  const pct = Math.min((used / limit) * 100, 100)
  const color = status === 'BREACH' ? 'error' : status === 'WARN' ? 'warning' : 'success'
  return <LinearProgress variant="determinate" value={pct} color={color}
    sx={{ height: 8, borderRadius: 4, my: 0.5 }} />
}

export default function Portfolio({ fundId }) {
  const [d, setD] = useState(null)
  const [err, setErr] = useState(null)
  const [showAll, setShowAll] = useState(false)

  useEffect(() => {
    let alive = true
    setD(null); setErr(null)
    Promise.all([api.fund(fundId), api.holdings(fundId), api.sectorExposure(fundId),
      api.cash(fundId), api.complianceLimits(fundId)])
      .then(([fund, holdings, sectors, cash, compliance]) =>
        alive && setD({ fund, holdings, sectors, cash, compliance }))
      .catch((e) => alive && setErr(e.message))
    return () => { alive = false }
  }, [fundId])

  if (err) return <Alert severity="error">{err}</Alert>
  if (!d) return <Box sx={{ display: 'grid', placeItems: 'center', py: 8 }}><CircularProgress /></Box>

  const { fund, holdings, sectors, cash, compliance } = d
  const shown = showAll ? holdings.holdings : holdings.holdings.slice(0, 10)

  return (
    <Stack spacing={2.5}>
      {/* KPIs — the fund's headline number leads with an accent rail */}
      <KpiGrid>
        <Stat accent label={fund.name} value={fmtCrValue(fund.aum_cr, 0)} sub={`AUM · ${fund.category}`} color="primary.main" />
        <Stat label="NAV (Direct-Growth)" value={fmtRupee(fund.nav)} sub={`${fund.holdings_count} holdings`} />
        <Stat label="Cash & Equivalents" value={fmtCrValue(cash.total_cash_cr, 0)} sub={`${fmtPct(cash.cash_pct)} of AUM`} color="secondary.main" />
        <Stat label="Benchmark" value={fund.benchmark} sub={`Mgr: ${fund.fund_manager}`} />
      </KpiGrid>

      {/* Bento: Holdings is the hero (wide, highlighted); exposure + compliance
          ride in a side rail that collapses under it on small screens. */}
      <Box sx={{ display: 'grid', gap: 2.5, alignItems: 'start',
        gridTemplateColumns: { xs: '1fr', lg: '1.6fr 1fr' } }}>
        <Panel highlight title="Holdings"
          action={(
            <Chip label={showAll ? 'Show top 10' : `Show all ${holdings.count}`} size="small"
              variant="outlined" onClick={() => setShowAll(!showAll)} clickable />
          )}>
          <ScrollX maxHeight={showAll ? 560 : undefined}>
            <Table size="small" stickyHeader>
              <TableHead>
                <TableRow>
                  <TableCell>Security</TableCell><TableCell>Sector</TableCell>
                  <TableCell align="right">Price</TableCell><TableCell align="right">Mkt Val</TableCell>
                  <TableCell align="right">Weight</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {shown.map((h) => (
                  <TableRow key={h.ticker} hover>
                    <TableCell>
                      <Stack direction="row" spacing={0.5} alignItems="center">
                        <Typography variant="body2" fontWeight={600}>{h.ticker}</Typography>
                        {h.has_lock_in && <LockIcon sx={{ fontSize: 14, color: 'warning.main' }} titleAccess={h.lock_in_reason} />}
                      </Stack>
                      <Typography variant="caption" color="text.secondary">{h.name}</Typography>
                    </TableCell>
                    <TableCell><Typography variant="body2" color="text.secondary">{h.sector}</Typography></TableCell>
                    <TableCell align="right">{fmtRupee(h.price, 0)}</TableCell>
                    <TableCell align="right">{fmtCrValue(h.market_value_cr, 0)}</TableCell>
                    <TableCell align="right">{fmtPct(h.weight)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </ScrollX>
        </Panel>

        <Stack spacing={2.5}>
          <Panel title="Sector Exposure">
            <SectorDonut sectors={sectors.sectors} />
          </Panel>

          <Panel title="Compliance — Top Utilisation">
            {[...compliance.utilization.issuers.slice(0, 3).map((r) => ({ ...r, kind: 'Issuer' })),
              ...compliance.utilization.sectors.slice(0, 2).map((r) => ({ ...r, kind: 'Sector' }))]
              .map((r) => (
                <Box key={r.kind + r.entity} sx={{ mb: 1 }}>
                  <Stack direction="row" justifyContent="space-between" alignItems="center">
                    <Typography variant="body2">
                      <Chip size="small" label={r.kind} variant="outlined" sx={{ mr: 1 }} />{r.entity}
                    </Typography>
                    <Typography variant="body2" color="text.secondary">
                      {fmtPct(r.used)} / {fmtPct(r.limit, 0)}
                    </Typography>
                  </Stack>
                  <Meter used={r.used} limit={r.limit} status={r.status} />
                </Box>
              ))}
          </Panel>
        </Stack>
      </Box>
    </Stack>
  )
}
