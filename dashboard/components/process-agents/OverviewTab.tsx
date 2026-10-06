import Link from "next/link";
import { Card } from "@/components/Card";
import { StatusBadge } from "@/components/StatusBadge";
import { StatCard } from "@/components/StatCard";
import type { ProcessAgentDetail, ProcessAgentStats } from "@/lib/types";
import { formatDate } from "./shared";

function formatSeconds(seconds: number | null): string {
  if (seconds === null || seconds === undefined) return "—";
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

function formatCount(value: number | null): string {
  return value === null || value === undefined ? "—" : String(value);
}

function formatScore(value: number | null): string {
  return value === null || value === undefined ? "—" : value.toFixed(1);
}

function InfoCard({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <Card className="p-4">
      <p className="text-xs font-medium text-text-muted uppercase tracking-wide">{label}</p>
      <div className="mt-1 text-sm font-semibold text-on-surface">{value}</div>
    </Card>
  );
}

export function OverviewTab({
  agent,
  stats,
  statsLoading,
  statsError,
}: {
  agent: ProcessAgentDetail;
  stats: ProcessAgentStats | null;
  statsLoading: boolean;
  statsError: string | null;
}) {
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
        <InfoCard label="Status" value={<StatusBadge status={agent.status} />} />
        <InfoCard label="Version" value={`v${agent.version}`} />
        <InfoCard label="Active" value={agent.is_active ? "Yes" : "No"} />
        <InfoCard
          label="Channel"
          value={
            <Link href={`/channels/${agent.channel}`} className="text-primary hover:underline">
              {agent.channel_name}
            </Link>
          }
        />
        <InfoCard label="Created" value={formatDate(agent.created_at)} />
        <InfoCard label="Updated" value={formatDate(agent.updated_at)} />
      </div>

      <div>
        <div className="flex items-end justify-between mb-3">
          <h2 className="text-sm font-semibold text-on-surface">Performance</h2>
        </div>
        {statsError ? (
          <div className="text-sm text-bad bg-bad/10 border border-bad/30 rounded-lg px-4 py-3">
            {statsError}
          </div>
        ) : (
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
            <StatCard label="Calls" value={statsLoading ? "…" : formatCount(stats?.calls ?? null)} />
            <StatCard
              label="Connected"
              value={statsLoading ? "…" : formatCount(stats?.connected ?? null)}
            />
            <StatCard
              label="Avg Duration"
              value={statsLoading ? "…" : formatSeconds(stats?.avg_duration_seconds ?? null)}
            />
            <StatCard
              label="QA Score"
              value={statsLoading ? "…" : formatScore(stats?.qa_score ?? null)}
            />
            <StatCard
              label="Hot Leads"
              value={statsLoading ? "…" : formatCount(stats?.hot_leads ?? null)}
            />
            <StatCard
              label="Callback Requests"
              value={statsLoading ? "…" : formatCount(stats?.callback_requests ?? null)}
            />
          </div>
        )}
        {!statsLoading && stats?.calls === 0 && (
          <p className="text-xs text-text-muted mt-2">
            Populates once this process starts running calls.
          </p>
        )}
      </div>
    </div>
  );
}
