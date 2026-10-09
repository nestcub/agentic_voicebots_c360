// Legacy card for components not yet moved to components/ui/card. Restyled
// onto the shared tokens so both kinds look the same.
export function Card({ className = "", style, children }: { className?: string; style?: React.CSSProperties; children: React.ReactNode }) {
  return (
    <div className={`bg-card text-card-foreground rounded-xl shadow-sm border border-border ${className}`} style={style}>
      {children}
    </div>
  );
}

export function CardHeader({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="px-5 pt-4 pb-2">
      <p className="text-base font-semibold text-foreground">{title}</p>
      {hint && <p className="text-xs text-muted-foreground mt-0.5">{hint}</p>}
    </div>
  );
}
