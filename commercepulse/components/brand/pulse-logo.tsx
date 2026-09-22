export function PulseLogo({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={className} aria-hidden>
      <rect width="32" height="32" rx="8" fill="currentColor" />
      <polyline
        points="5,17 9,17 11,9 15,24 19,12 21,17 27,17"
        fill="none"
        stroke="#042f2e"
        strokeWidth="2.2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
