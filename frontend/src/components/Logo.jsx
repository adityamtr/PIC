// PIC Tool brand mark: a gradient tile carrying a stroked "P" monogram (PIC =
// Portfolio Investment Committee) with an approval-check badge overlapping the
// bottom-right corner, signalling the review/decision workflow the app drives.
// A top sheen and inner hairline give it depth; scales cleanly at any size.
export function Logo({ size = 36, rounded = 12 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 40 40" fill="none"
      xmlns="http://www.w3.org/2000/svg" role="img" aria-label="PIC Tool">
      <defs>
        <linearGradient id="pic-grad" x1="4" y1="2" x2="36" y2="38" gradientUnits="userSpaceOnUse">
          <stop stopColor="#6366F1" />
          <stop offset="0.5" stopColor="#8B5CF6" />
          <stop offset="1" stopColor="#06B6D4" />
        </linearGradient>
        <linearGradient id="pic-sheen" x1="20" y1="0" x2="20" y2="24" gradientUnits="userSpaceOnUse">
          <stop stopColor="#fff" stopOpacity="0.22" />
          <stop offset="1" stopColor="#fff" stopOpacity="0" />
        </linearGradient>
      </defs>
      <rect width="40" height="40" rx={rounded} fill="url(#pic-grad)" />
      <rect width="40" height="40" rx={rounded} fill="url(#pic-sheen)" />
      <rect x="0.6" y="0.6" width="38.8" height="38.8" rx={rounded - 0.6}
        fill="none" stroke="#fff" strokeOpacity="0.18" strokeWidth="1.2" />
      {/* stroked "P" monogram */}
      <path d="M13.5 29.5 V10.5 H21.5 C26.5 10.5 26.5 19.5 21.5 19.5 H13.5"
        stroke="#fff" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" fill="none" />
      {/* approval-check badge: the PIC's sign-off on a reviewed plan */}
      <circle cx="29.5" cy="29.5" r="7" fill="#fff" fillOpacity="0.95" />
      <path d="M26.3 29.6 L28.7 32 L32.8 26.8"
        stroke="#4F46E5" strokeWidth="2.3" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}
