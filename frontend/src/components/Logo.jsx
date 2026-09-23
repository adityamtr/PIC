// WealthVector brand mark: a gradient tile carrying an ascending "W" chart-line
// that resolves into a rising vector arrow — Wealth (the W / upward book value)
// + Vector (the directed arrow). Valley nodes read it as a growth chart; a top
// sheen and inner hairline give it depth. Scales cleanly at any size.
export function Logo({ size = 36, rounded = 12 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 40 40" fill="none"
      xmlns="http://www.w3.org/2000/svg" role="img" aria-label="WealthVector">
      <defs>
        <linearGradient id="wv-grad" x1="4" y1="2" x2="36" y2="38" gradientUnits="userSpaceOnUse">
          <stop stopColor="#6366F1" />
          <stop offset="0.5" stopColor="#8B5CF6" />
          <stop offset="1" stopColor="#06B6D4" />
        </linearGradient>
        <linearGradient id="wv-sheen" x1="20" y1="0" x2="20" y2="24" gradientUnits="userSpaceOnUse">
          <stop stopColor="#fff" stopOpacity="0.22" />
          <stop offset="1" stopColor="#fff" stopOpacity="0" />
        </linearGradient>
      </defs>
      <rect width="40" height="40" rx={rounded} fill="url(#wv-grad)" />
      <rect width="40" height="40" rx={rounded} fill="url(#wv-sheen)" />
      <rect x="0.6" y="0.6" width="38.8" height="38.8" rx={rounded - 0.6}
        fill="none" stroke="#fff" strokeOpacity="0.18" strokeWidth="1.2" />
      {/* ascending W that trends upward like a growth chart */}
      <path d="M7.5 24 L13.5 29.5 L20 21 L26.5 27.5 L32 12"
        stroke="#fff" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
      {/* direction-aligned arrowhead -> the vector tip */}
      <path d="M27.8 15.6 L32 12 L33 17.4"
        stroke="#fff" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
      {/* valley data-points */}
      <circle cx="13.5" cy="29.5" r="1.4" fill="#fff" fillOpacity="0.92" />
      <circle cx="26.5" cy="27.5" r="1.4" fill="#fff" fillOpacity="0.92" />
    </svg>
  )
}
