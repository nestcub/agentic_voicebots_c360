"use client";

import { useScoped } from "@/lib/useScoped";
import { StatCard } from "@/components/StatCard";
import { ProgressBar } from "@/components/ProgressBar";
import { Card, CardHeader } from "@/components/Card";
import { StatusBadge } from "@/components/StatusBadge";
import { domainConfig } from "@/lib/domainConfig";
import type { Kpis, TargetProgress, Commitment, Lead } from "@/lib/types";

const EMPTY_KPIS: Kpis = {
  total_leads: 0, pending: 0, calling: 0, booked: 0, not_interested: 0, follow_up: 0, conversion_rate: 0,
};
const EMPTY_PROGRESS: TargetProgress = {
  reach_out: { actual: 0, target: 0 }, close: { actual: 0, target: 0 }, follow_up: { actual: 0, target: 0 },
};

export default function DashboardPage() {
  const { data: kpis } = useScoped<Kpis>((ds, s) => ds.getKpis(s), EMPTY_KPIS);
  const { data: progress } = useScoped<TargetProgress>((ds, s) => ds.getTargetProgress(s), EMPTY_PROGRESS);
  const { data: commitments } = useScoped<Commitment[]>((ds, s) => ds.getCommitments(s), []);
  const { data: leads } = useScoped<Lead[]>((ds, s) => ds.getLeads(s), []);

  const now = Date.now();
  const overdue = commitments.filter((c) => c.state === "pending" && new Date(c.due_at).getTime() < now);

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-slate-900">Dashboard</h1>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard label={domainConfig.metrics.totalLeads} value={kpis.total_leads} />
        <StatCard label={domainConfig.metrics.booked} value={kpis.booked}
          sub={`${Math.round(kpis.conversion_rate * 100)}% conversion`} />
        <StatCard label={domainConfig.metrics.followUps} value={kpis.follow_up} />
        <StatCard label="Overdue follow-ups" value={overdue.length}
          sub={overdue.length ? "needs attention" : "all on time"} />
      </div>

      <div className="grid md:grid-cols-2 gap-6">
        <Card className="p-5 space-y-4">
          <CardHeader title="Target progress" hint="Actual vs monthly target" />
          <ProgressBar label={domainConfig.metrics.reachOut} pair={progress.reach_out} />
          <ProgressBar label={domainConfig.metrics.close} pair={progress.close} />
          <ProgressBar label={domainConfig.metrics.followUps} pair={progress.follow_up} />
        </Card>

        <Card className="p-0 overflow-hidden">
          <CardHeader title="Recent leads" hint={`${leads.length} in scope`} />
          <div className="divide-y divide-slate-100">
            {leads.slice(0, 6).map((l) => (
              <div key={l.id} className="flex items-center justify-between px-5 py-2.5">
                <div>
                  <p className="text-sm font-medium text-slate-800">{l.name}</p>
                  <p className="text-xs text-slate-500">{l.vehicle_model} · {l.branch}</p>
                </div>
                <StatusBadge status={l.status} />
              </div>
            ))}
            {leads.length === 0 && <p className="px-5 py-6 text-sm text-slate-400">No leads in scope.</p>}
          </div>
        </Card>
      </div>
    </div>
  );
}
