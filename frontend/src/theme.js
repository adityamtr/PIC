import { createTheme } from '@mui/material/styles'

// Fresh, bright palette: vivid indigo/violet primary + cyan secondary, with a
// signature gradient used on the brand mark and primary actions.
export const BRAND_GRADIENT = 'linear-gradient(135deg, #6366F1 0%, #8B5CF6 50%, #06B6D4 100%)'

export function buildTheme(mode) {
  const isLight = mode === 'light'
  return createTheme({
    palette: {
      mode,
      primary: { main: '#6366F1', light: '#818CF8', dark: '#4F46E5', contrastText: '#fff' },
      secondary: { main: '#06B6D4', light: '#22D3EE', dark: '#0891B2', contrastText: '#fff' },
      success: { main: '#14B8A6', light: '#2DD4BF', dark: '#0D9488' },   // teal, not grassy green
      warning: { main: '#F97316', light: '#FB923C', dark: '#EA580C' },   // vivid orange, not yellow
      error: { main: '#F43F5E', light: '#FB7185', dark: '#E11D48' },     // rose
      info: { main: '#3B82F6' },
      background: isLight
        ? { default: '#F5F6FE', paper: '#FFFFFF' }
        : { default: '#0B1020', paper: '#151B2E' },
      divider: isLight ? '#E7E9F5' : '#28304A',
    },
    shape: { borderRadius: 16 },
    typography: {
      fontFamily: 'Roboto, "Segoe UI", system-ui, -apple-system, sans-serif',
      h6: { fontWeight: 700 },
      subtitle2: { fontWeight: 700, letterSpacing: 0.4 },
      button: { textTransform: 'none', fontWeight: 600 },
    },
    components: {
      MuiCard: {
        defaultProps: { elevation: 0 },
        styleOverrides: {
          root: {
            border: isLight ? '1px solid #ECEEFB' : '1px solid #28304A',
            boxShadow: isLight
              ? '0 1px 2px rgba(16,24,64,0.04), 0 8px 24px rgba(99,102,241,0.06)'
              : '0 1px 2px rgba(0,0,0,0.4)',
            transition: 'box-shadow .25s ease, transform .25s ease',
          },
        },
      },
      MuiButton: {
        defaultProps: { disableElevation: true },
        styleOverrides: {
          containedPrimary: { background: BRAND_GRADIENT, '&:hover': { filter: 'brightness(1.05)' } },
        },
      },
      MuiChip: { styleOverrides: { root: { fontWeight: 600 } } },
      MuiLinearProgress: { styleOverrides: { root: { borderRadius: 6 } } },
      MuiAppBar: { styleOverrides: { root: { backdropFilter: 'blur(8px)' } } },
      MuiToggleButton: {
        styleOverrides: {
          root: {
            '&.Mui-selected': {
              background: 'rgba(99,102,241,0.14)',
              color: isLight ? '#4F46E5' : '#A5B4FC',
              '&:hover': { background: 'rgba(99,102,241,0.2)' },
            },
          },
        },
      },
    },
  })
}
