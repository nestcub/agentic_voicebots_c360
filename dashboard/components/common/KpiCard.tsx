import type { LucideIcon } from "lucide-react";
import { Card } from "@/components/ui/card";

// Icon-circle colour per KPI, matching the dashboard mock's blue / green / purple / orange.
const KPI_TONES = {
  blue: "bg-blue-600",
  green: "bg-emerald-500",
  purple: "bg-violet-500",
  orange: "bg-amber-400",
} as const;

export type KpiTone = keyof typeof KPI_TONES;

export function KpiCard({
  label,
  value,
  hint,
  icon: Icon,
  tone,
}: {
  label: string;
  value: string;
  hint?: string;
  icon: LucideIcon;
  tone: KpiTone;
}) {
  return (
    <Card className="p-5 flex-row items-start gap-4">
      <div className={`w-12 h-12 shrink-0 rounded-full ${KPI_TONES[tone]} flex items-center justify-center`}>
        <Icon className="w-6 h-6 text-white" />
      </div>
      <div className="min-w-0">
        <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">{label}</p>
        <p className="text-3xl font-bold text-foreground mt-1">{value}</p>
        {hint && <p className="text-xs text-muted-foreground mt-1">{hint}</p>}
      </div>
    </Card>
  );
}

export function MiniStat({ label, value, icon: Icon }: { label: string; value: string; icon: LucideIcon }) {
  return (
    <Card className="p-4 flex-row items-center gap-3">
      <div className="w-10 h-10 shrink-0 rounded-lg bg-accent flex items-center justify-center">
        <Icon className="w-5 h-5 text-primary" />
      </div>
      <div className="min-w-0">
        <p className="text-xs font-medium text-muted-foreground">{label}</p>
        <p className="text-xl font-bold text-foreground">{value}</p>
      </div>
    </Card>
  );
}
