import type { ReactNode } from "react";

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <div className={`rounded-2xl bg-white border border-slate-200/70 shadow-sm ${className}`}>
      {children}
    </div>
  );
}

export function CardHeader({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="px-5 pt-4 pb-2">
      <h3 className="text-sm font-semibold text-slate-800">{title}</h3>
      {hint && <p className="text-xs text-slate-500 mt-0.5">{hint}</p>}
    </div>
  );
}
