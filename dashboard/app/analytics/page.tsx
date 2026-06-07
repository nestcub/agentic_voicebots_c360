"use client";

import { useScoped } from "@/lib/useScoped";
import { Card, CardHeader } from "@/components/Card";
import { StatCard } from "@/components/StatCard";
import type { Report, ScopeBreakdown } from "@/lib/types";

const EMPTY: Report = {
  period: "", scope: { level: "all" }, by_region: [], by_branch: [], outcomes_over_time: [], goal_attainment: 0,
};

function BreakdownTable({ title, rows }: { title: string; rows: ScopeBreakdown[] }) {
  const max = Math.max(1, ...rows.map((r) => r.leads));
  return (
    <Card className="p-0 overflow-hidden">
      <CardHeader title={title} />
      <div className="px-5 pb-4 space-y-2">
        {rows.map((r) => (
          <div key={r.name}>
            <div className="flex justify-between text-sm">
              <span className="text-slate-700">{r.name}</span>
              <span className="text-slate-500">
                {r.leads} leads · {r.booked} booked · {Math.round(r.conversion * 100)}%
              </span>
            </div>
            <div className="h-2 w-full rounded-full bg-slate-100 mt-1 overflow-hidden">
              <div className="h-full rounded-full bg-primary-container" style={{ width: `${(r.leads / max) * 100}%` }} />
            </div>
          </div>
        ))}
        {rows.length === 0 && <p className="text-sm text-slate-400 py-4">No data in scope.</p>}
      </div>
    </Card>
  );
}

export default function AnalyticsPage() {
  const { data: report } = useScoped<Report>((ds, s) => ds.getReport(s), EMPTY);
  const maxCalls = Math.max(1, ...report.outcomes_over_time.map((t) => t.calls));

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-slate-900">Analytics & Reports</h1>

      <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
        <StatCard label="Goal attainment" value={`${Math.round(report.goal_attainment * 100)}%`}
          sub="booked vs target" />
        <StatCard label="Regions" value={report.by_region.length} />
        <StatCard label="Branches active" value={report.by_branch.length} />
      </div>

      <div className="grid md:grid-cols-2 gap-6">
        <BreakdownTable title="By region" rows={report.by_region} />
        <BreakdownTable title="By branch" rows={report.by_branch} />
      </div>

      <Card className="p-0 overflow-hidden">
        <CardHeader title="Calls & bookings over time" />
        <div className="px-5 pb-5 pt-2 flex items-end gap-2 h-44">
          {report.outcomes_over_time.map((t) => (
            <div key={t.date} className="flex-1 flex flex-col items-center justify-end gap-1">
              <div className="w-full flex flex-col justify-end items-center gap-0.5" style={{ height: "120px" }}>
                <div className="w-full rounded-t bg-emerald-400" style={{ height: `${(t.booked / maxCalls) * 120}px` }} />
                <div className="w-full rounded-t bg-primary-container" style={{ height: `${(t.calls / maxCalls) * 120}px` }} />
              </div>
              <span className="text-[10px] text-slate-400">{t.date.slice(5)}</span>
            </div>
          ))}
          {report.outcomes_over_time.length === 0 && <p className="text-sm text-slate-400">No call data in scope.</p>}
        </div>
        <div className="px-5 pb-4 flex gap-4 text-xs text-slate-500">
          <span className="flex items-center gap-1"><i className="w-3 h-3 rounded-sm bg-primary-container inline-block" /> calls</span>
          <span className="flex items-center gap-1"><i className="w-3 h-3 rounded-sm bg-emerald-400 inline-block" /> booked</span>
        </div>
      </Card>
    </div>
  );
}
