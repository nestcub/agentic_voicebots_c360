import type { ProgressPair } from "@/lib/types";

export function ProgressBar({ label, pair }: { label: string; pair: ProgressPair }) {
  const pct = pair.target > 0 ? Math.min(100, Math.round((pair.actual / pair.target) * 100)) : 0;
  const color = pct >= 80 ? "bg-emerald-500" : pct >= 50 ? "bg-amber-500" : "bg-rose-500";
  return (
    <div>
      <div className="flex justify-between text-sm mb-1">
        <span className="font-medium text-slate-700">{label}</span>
        <span className="text-slate-500">
          {pair.actual} / {pair.target} <span className="text-slate-400">({pct}%)</span>
        </span>
      </div>
      <div className="h-2.5 w-full rounded-full bg-slate-100 overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}
