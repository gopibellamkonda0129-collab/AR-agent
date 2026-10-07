"use client";

/**
 * AR Agent brand mark — a quiet graphite tile with a clean "AR" monogram
 * and a small up-right cash-in arrow. Restrained, one accent, no glow.
 */
export function LogoMark({ size = 38, className }: { size?: number; className?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 48 48" className={className} role="img" aria-label="AR Agent">
      <rect x="1" y="1" width="46" height="46" rx="9" fill="#10131d" />
      <rect x="1.5" y="1.5" width="45" height="45" rx="8.5" fill="none" stroke="#ffffff" strokeOpacity="0.1" strokeWidth="1" />
      <rect x="1.5" y="1.5" width="45" height="22" rx="8.5" fill="url(#lg-top)" />
      <text
        x="22.5"
        y="31"
        textAnchor="middle"
        fontFamily="Inter, SF Pro Text, system-ui, sans-serif"
        fontWeight="600"
        fontSize="19"
        letterSpacing="-0.5"
        fill="#f2f4f8"
        style={{ fontVariantLigatures: "none" }}
      >
        AR
      </text>
      <path
        d="M33.5 33.5 L40.5 26.5 M36 26.5 L40.5 26.5 L40.5 31"
        fill="none"
        stroke="#7c8cff"
        strokeWidth="2.2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <defs>
        <linearGradient id="lg-top" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#ffffff" stopOpacity="0.05" />
          <stop offset="1" stopColor="#ffffff" stopOpacity="0" />
        </linearGradient>
      </defs>
    </svg>
  );
}

/** Logo + wordmark lockup for the sidebar. */
export function LogoLockup({ size = 36 }: { size?: number }) {
  return (
    <span className="brand-lockup">
      <LogoMark size={size} />
      <span>
        <span className="brand-name">AR Agent</span>
        <span className="brand-sub">Receivables Assistant</span>
      </span>
    </span>
  );
}