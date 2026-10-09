import Link from "next/link";
import { CalendarClock, CalendarPlus, Clock, Flame, Network, Phone, PhoneCall, RefreshCw, Star, Target } from "lucide-react";
import { Card } from "@/components/ui/card";
import { KpiCard, MiniStat } from "@/components/common/KpiCard";
import { ErrorAlert } from "@/components/common/ErrorAlert";
import type { ProcessAgentDetail, ProcessAgentStats } from "@/lib/types";
import { formatDuration, formatPercent, formatScore } from "@/lib/format";
import { formatDate } from "./shared";

function formatCount(value: number | null): string {
  return value === null || value === undefined ? "—" : String(value);
}

function InfoItem({
  icon: Icon,
  label,
  value,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value: React.ReactNode;
}) {
  return (
    <div className="flex items-center gap-3 min-w-0">
      <span className="w-9 h-9 shrink-0 rounded-lg bg-muted text-muted-foreground flex items-center justify-center">
        <Icon className="w-4 h-4" />
      </span>
      <div className="min-w-0">
        <p className="text-xs text-muted-foreground">{label}</p>
        <div className="text-sm font-medium text-foreground truncate">{value}</div>
      </div>
    </div>
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
  const show = (value: string) => (statsLoading ? "…" : value);
  const calls = stats?.calls ?? null;
  const connected = stats?.connected ?? null;
  const connectRate = calls !== null && connected !== null && calls > 0 ? connected / calls : null;

  return (
    <div className="space-y-6">
      <Card className="p-5 gap-0">
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-5">
          <InfoItem
            icon={Network}
            label="Channel"
            value={
              <Link href={`/channels/${agent.channel}`} className="text-primary hover:underline">
                {agent.channel_name}
              </Link>
            }
          />
          <InfoItem icon={CalendarPlus} label="Created" value={formatDate(agent.created_at)} />
          <InfoItem icon={RefreshCw} label="Updated" value={formatDate(agent.updated_at)} />
        </div>
      </Card>

      <div className="space-y-3">
        <h2 className="text-sm font-semibold text-foreground">Performance</h2>
        {statsError ? (
          <ErrorAlert message={statsError} />
        ) : (
          <>
            <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
              <KpiCard label="Calls" value={show(formatCount(calls))} icon={Phone} tone="blue" />
              <KpiCard label="Connected" value={show(formatCount(connected))} icon={PhoneCall} tone="green" />
              <KpiCard
                label="Connect Rate"
                value={show(formatPercent(connectRate))}
                hint="Connected ÷ total calls"
                icon={Target}
                tone="purple"
              />
              <KpiCard
                label="Avg. Duration"
                value={show(formatDuration(stats?.avg_duration_seconds ?? null))}
                icon={Clock}
                tone="orange"
              />
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
              <MiniStat label="QA Score" value={show(formatScore(stats?.qa_score ?? null))} icon={Star} />
              <MiniStat label="Hot Leads" value={show(formatCount(stats?.hot_leads ?? null))} icon={Flame} />
              <MiniStat
                label="Callback Requests"
                value={show(formatCount(stats?.callback_requests ?? null))}
                icon={CalendarClock}
              />
            </div>
          </>
        )}
        {!statsLoading && stats?.calls === 0 && (
          <p className="text-xs text-muted-foreground">Populates once this process starts running calls.</p>
        )}
      </div>
    </div>
  );
}
