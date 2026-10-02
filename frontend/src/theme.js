import { createTheme } from '@mui/material/styles'

// Teal, blue, and amber keep the finance UI crisp without leaning on one hue.
export const BRAND_GRADIENT = 'linear-gradient(125deg, #087F70 0%, #317E9E 62%, #C77917 130%)'

export function buildTheme(mode) {
  const isLight = mode === 'light'
  return createTheme({
    palette: {
      mode,
      primary: { main: '#087F70', light: '#25A18E', dark: '#066357', contrastText: '#fff' },
      secondary: { main: '#317E9E', light: '#5A9DB7', dark: '#245F78', contrastText: '#fff' },
      success: { main: '#138A68', light: '#36A886', dark: '#0D6E52' },
      warning: { main: '#C77917', light: '#E09A3E', dark: '#9F5E10' },
      error: { main: '#C65353', light: '#DE7373', dark: '#A93D3D' },
      info: { main: '#2874C7' },
      background: isLight
        ? { default: '#F3F7F6', paper: '#FFFFFF' }
        : { default: '#101A1D', paper: '#172326' },
      divider: isLight ? '#DDE7E4' : '#2C3C3E',
    },
    shape: { borderRadius: 8 },
    typography: {
      fontFamily: 'Roboto, "Segoe UI", system-ui, -apple-system, sans-serif',
      h6: { fontWeight: 700 },
      subtitle2: { fontWeight: 700, letterSpacing: 0 },
      button: { textTransform: 'none', fontWeight: 600 },
    },
    components: {
      MuiCard: {
        defaultProps: { elevation: 0 },
        styleOverrides: {
          root: {
            border: isLight ? '1px solid #E1EAE7' : '1px solid #2C3C3E',
            boxShadow: isLight
              ? '0 1px 2px rgba(18,52,47,0.04), 0 8px 22px rgba(27,79,69,0.055)'
              : '0 1px 2px rgba(0,0,0,0.4)',
            transition: 'box-shadow .2s ease, transform .2s ease, border-color .2s ease',
            '@media (hover: hover)': {
              '&:hover': {
                transform: 'translateY(-1px)',
                boxShadow: isLight
                  ? '0 4px 14px rgba(18,52,47,0.10)'
                  : '0 4px 14px rgba(0,0,0,0.28)',
              },
            },
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
              background: isLight ? 'rgba(8,127,112,0.12)' : 'rgba(37,161,142,0.2)',
              color: isLight ? '#066357' : '#69C4B3',
              '&:hover': { background: isLight ? 'rgba(8,127,112,0.18)' : 'rgba(37,161,142,0.26)' },
            },
          },
        },
      },
    },
  })
}
