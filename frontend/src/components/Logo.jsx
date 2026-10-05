// PIC Tool stitched monogram with a verified-status badge.
export function Logo({ size = 36, rounded = 12, mode = 'light' }) {
  const surface = mode === 'dark' ? '#172326' : '#FFFFFF'

  return (
    <svg width={size} height={size} viewBox="0 0 40 40" fill="none"
      xmlns="http://www.w3.org/2000/svg" role="img" aria-label="PIC Tool">
      <defs>
        <linearGradient id="pic-grad" x1="4" y1="2" x2="36" y2="38" gradientUnits="userSpaceOnUse">
          <stop stopColor="#087F70" />
          <stop offset="0.62" stopColor="#317E9E" />
          <stop offset="1" stopColor="#C77917" />
        </linearGradient>
      </defs>
      <rect width="40" height="40" rx={rounded} fill="url(#pic-grad)" />
      <rect x="2.5" y="2.5" width="35" height="35" rx={Math.max(rounded - 3, 1)}
        fill="none" stroke="#FFFFFF" strokeOpacity="0.58" strokeWidth="1.1"
        strokeDasharray="2 2" />
      <text x="20" y="27" textAnchor="middle" fill="#FFFFFF"
        fontFamily="Arial, sans-serif" fontSize="23" fontWeight="800">P</text>
      <circle cx="32" cy="32" r="7" fill={surface} />
      <circle cx="32" cy="32" r="5.5" fill="#138A68" />
      <path d="m29.5 32 1.7 1.7 3.4-3.8" stroke="#FFFFFF" strokeWidth="1.5"
        strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}
