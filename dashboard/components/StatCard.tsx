import { Card } from "./Card";

type CardColor = 'red' | 'blue' | 'green' | 'orange';

const BG: Record<CardColor, string> = {
  red:    'bg-red-500',
  blue:   'bg-blue-500',
  green:  'bg-emerald-500',
  orange: 'bg-orange-500',
};

interface StatCardProps {
  label: string;
  value: string | number;
  sub?: string;
  color?: CardColor;
  icon?: React.ReactNode;
}

export function StatCard({ label, value, sub, color, icon }: StatCardProps) {
  if (color) {
    return (
      <div className={`${BG[color]} rounded-xl p-5 flex items-center gap-4`}>
        {icon && (
          <div className="w-12 h-12 bg-white/20 rounded-lg flex items-center justify-center text-2xl text-white shrink-0">
            {icon}
          </div>
        )}
        <div>
          <p className="text-sm text-white/80">{label}</p>
          <p className="text-3xl font-bold text-white">{value}</p>
          {sub && <p className="text-xs text-white/70 mt-0.5">{sub}</p>}
        </div>
      </div>
    );
  }

  return (
    <Card className="p-5">
      <p className="text-xs font-medium text-slate-500 uppercase tracking-wide">{label}</p>
      <p className="text-3xl font-bold text-slate-900 mt-1">{value}</p>
      {sub && <p className="text-xs text-slate-500 mt-1">{sub}</p>}
    </Card>
  );
}
