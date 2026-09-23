import { useEffect, useState } from 'react'
import {
  Alert, Box, Chip, CircularProgress, LinearProgress, Stack, Table, TableBody,
  TableCell, TableHead, TableRow, Typography,
} from '@mui/material'
import { api } from '../api'
import { fmtCrValue, fmtNum, fmtRupee } from '../format'
import { Panel, ScrollX } from './ui'

function CashCell({ cr }) {
  return (
    <TableCell align="right" sx={{ color: cr < 0 ? 'error.main' : 'success.main', fontWeight: 600 }}>
      {fmtCrValue(cr)}
    </TableCell>
  )
}

function TradeTable({ trades, showStatus }) {
  return (
    <ScrollX>
      <Table size="small" stickyHeader>
        <TableHead>
          <TableRow>
            <TableCell>Trade ID</TableCell><TableCell>Security</TableCell><TableCell>Side</TableCell>
            <TableCell align="right">Shares</TableCell><TableCell align="right">Price</TableCell>
            <TableCell align="right">Cash Impact</TableCell><TableCell>Trade Date</TableCell>
            <TableCell>Settlement</TableCell><TableCell>Cycle</TableCell>
            {showStatus && <TableCell>Status</TableCell>}
          </TableRow>
        </TableHead>
        <TableBody>
          {trades.map((t) => (
            <TableRow key={t.trade_id} hover>
              <TableCell><Typography variant="caption" color="text.secondary">{t.trade_id}</Typography></TableCell>
              <TableCell><Typography variant="body2" fontWeight={600}>{t.ticker}</Typography></TableCell>
              <TableCell>
                <Chip size="small" label={t.side} color={t.side === 'BUY' ? 'success' : 'error'} variant="outlined" />
              </TableCell>
              <TableCell align="right">{fmtNum(t.shares)}</TableCell>
              <TableCell align="right">{fmtRupee(t.price, 0)}</TableCell>
              <CashCell cr={t.cash_impact_cr} />
              <TableCell><Typography variant="body2" color="text.secondary">{t.trade_date}</Typography></TableCell>
              <TableCell><Typography variant="body2">{t.settlement_date}</Typography></TableCell>
              <TableCell>
                <Chip size="small" label={t.cycle}
                  color={t.cycle === 'T+1' ? 'primary' : 'secondary'} variant="filled"
                  sx={{ fontWeight: 700 }} />
              </TableCell>
              {showStatus && <TableCell>
                <Chip size="small" label={t.status}
                  color={t.status === 'Settled' ? 'default' : 'warning'} variant="outlined" />
              </TableCell>}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </ScrollX>
  )
}

export default function Trades({ fundId }) {
  const [d, setD] = useState(null)
  const [err, setErr] = useState(null)

  useEffect(() => {
    let alive = true
    setD(null); setErr(null)
    Promise.all([api.pendingTrades(fundId), api.executedTrades(fundId)])
      .then(([pending, executed]) => alive && setD({ pending, executed }))
      .catch((e) => alive && setErr(e.message))
    return () => { alive = false }
  }, [fundId])

  if (err) return <Alert severity="error">{err}</Alert>
  if (!d) return <Box sx={{ display: 'grid', placeItems: 'center', py: 8 }}><CircularProgress /></Box>

  const { pending, executed } = d
  const maxCycle = Math.max(1, ...pending.by_cycle.map((c) => c.count))

  return (
    <Stack spacing={2.5}>
      {/* Summary bento: a hero net-impact tile beside the cycle breakdown. */}
      <Box sx={{ display: 'grid', gap: 2.5, alignItems: 'stretch',
        gridTemplateColumns: { xs: '1fr', md: '1fr 1.4fr' } }}>
        <Panel highlight title="Net Settlement Impact" bodySx={{ display: 'flex', flexDirection: 'column' }}>
          <Typography variant="h3" fontWeight={800}
            sx={{ color: pending.net_cash_impact_cr < 0 ? 'error.main' : 'success.main', lineHeight: 1.1 }}>
            {fmtCrValue(pending.net_cash_impact_cr)}
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
            across <strong>{pending.count}</strong> pending trades ·{' '}
            {pending.net_cash_impact_cr < 0 ? 'cash to be paid out' : 'cash to be received'}
          </Typography>
        </Panel>

        <Panel title="By Settlement Cycle">
          <Stack spacing={1.75} sx={{ mt: 0.5 }}>
            {pending.by_cycle.map((c) => (
              <Box key={c.cycle}>
                <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 0.5 }}>
                  <Chip size="small" label={c.cycle} color={c.cycle === 'T+1' ? 'primary' : 'secondary'} />
                  <Typography variant="body2" fontWeight={600}>{c.count} trades</Typography>
                  <Box sx={{ flexGrow: 1 }} />
                  <Typography variant="body2" sx={{ color: c.net_cr < 0 ? 'error.main' : 'success.main', fontWeight: 600 }}>
                    net {fmtCrValue(c.net_cr)}
                  </Typography>
                </Stack>
                <LinearProgress variant="determinate" value={(c.count / maxCycle) * 100}
                  color={c.cycle === 'T+1' ? 'primary' : 'secondary'}
                  sx={{ height: 8, borderRadius: 4 }} />
              </Box>
            ))}
          </Stack>
        </Panel>
      </Box>

      {/* Actionable hero: unsettled trades */}
      <Panel highlight title="Pending / Unsettled Trades"
        subtitle="Cash committed but not yet moved. Settlement follows the Indian T+1 rolling cycle (some legs T+2).">
        <TradeTable trades={pending.trades} showStatus />
      </Panel>

      {/* Secondary: settled history, visually de-emphasised */}
      <Panel title="Previously Executed (Settled) Trades" sx={{ bgcolor: 'action.hover' }}>
        <TradeTable trades={executed.trades} showStatus />
      </Panel>
    </Stack>
  )
}
