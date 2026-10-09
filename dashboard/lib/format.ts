// Display formatters shared across pages. Each returns "—" for null so a
// missing metric reads as "no data yet" rather than a fabricated 0.

export function formatDuration(seconds: number | null): string {
  if (seconds === null) return "—";
  const mins = Math.floor(seconds / 60);
  const secs = Math.round(seconds % 60);
  return `${mins}:${secs.toString().padStart(2, "0")}`;
}

export function formatPercent(ratio: number | null): string {
  if (ratio === null) return "—";
  return `${Math.round(ratio * 100)}%`;
}

export function formatScore(score: number | null): string {
  if (score === null) return "—";
  return score.toFixed(1);
}
