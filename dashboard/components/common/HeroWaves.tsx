import { useId } from "react";

// Decorative soft hills + audio waveform, drawn inline so there's no image asset.
// Used by the Dashboard hero banner and the login page's brand panel.
export function HeroWaves({ className = "", centerX = 380 }: { className?: string; centerX?: number }) {
  const gradientId = useId();
  const bars = [4, 7, 10, 14, 9, 18, 26, 34, 22, 40, 56, 30, 20, 34, 14, 10, 7, 5, 4];
  const barGap = 9;
  const startX = centerX - ((bars.length - 1) * barGap) / 2;
  return (
    <svg viewBox="0 0 600 200" preserveAspectRatio="xMidYMid slice" className={className} aria-hidden="true">
      <defs>
        <linearGradient id={gradientId} x1="0" x2="1" y1="0" y2="0">
          <stop offset="0" stopColor="#93c5fd" />
          <stop offset="0.5" stopColor="#4f46e5" />
          <stop offset="1" stopColor="#c4b5fd" />
        </linearGradient>
      </defs>
      <path d="M0 200 C120 120 220 90 330 130 C430 165 500 70 600 90 L600 200 Z" fill="#c7d2fe" opacity="0.35" />
      <path d="M0 200 C150 150 260 160 360 170 C460 180 520 130 600 140 L600 200 Z" fill="#a5b4fc" opacity="0.25" />
      {bars.map((h, i) => (
        <rect
          key={i}
          x={startX + i * barGap - 2}
          y={90 - h / 2}
          width={4}
          height={h}
          rx={2}
          fill={`url(#${gradientId})`}
        />
      ))}
    </svg>
  );
}
