"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  Phone,
  PhoneCall,
  Target,
  Clock,
  Network,
  Plus,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { KpiCard } from "@/components/common/KpiCard";
import { EmptyState } from "@/components/common/EmptyState";
import { ErrorAlert } from "@/components/common/ErrorAlert";
import { DealerCallsCard } from "@/components/DealerCallsCard";
import { demoCallsFor } from "@/lib/demoCalls";
import { str } from "@/components/process-agents/shared";
import {
  listChannels,
  listProcessAgents,
  getProcessAgentStats,
  getProcessAgentCalls,
} from "@/lib/telehubApi";
import { formatDuration, formatPercent } from "@/lib/format";
import type { CallRow, Channel, ProcessAgentStats, ProcessAgentSummary } from "@/lib/types";

// Aggregated across every ProcessAgent in the selected channel — each field
// stays null (renders "—") when no process agent contributed any data for
// it, same fail-open convention as ProcessAgentStats itself.
interface ChannelOverview {
  calls: number;
  connected: number;
  avgDurationSeconds: number | null;
  connectRate: number | null; // connected / calls
}

interface AgentStats {
  agent: ProcessAgentSummary;
  stats: ProcessAgentStats;
  calls: CallRow[];
}

function isTestCall(row: CallRow): boolean {
  return ["true", "1", "yes"].includes(str(row.variables.is_test).trim().toLowerCase());
}

function aggregateStats(stats: ProcessAgentStats[]): ChannelOverview {
  const calls = stats.reduce((sum, s) => sum + s.calls, 0);
  const connected = stats.reduce((sum, s) => sum + s.connected, 0);

  // Weight per-agent averages by their own connected counts so one
  // low-volume agent doesn't skew the channel-wide average as much as one
  // that's actually handled most of the calls.
  const durationWeighted = stats.reduce(
    (acc, s) => (s.avg_duration_seconds !== null ? acc + s.avg_duration_seconds * s.connected : acc),
    0,
  );
  const avgDurationSeconds = connected > 0 && durationWeighted > 0 ? durationWeighted / connected : null;

  return {
    calls,
    connected,
    avgDurationSeconds,
    connectRate: calls > 0 ? connected / calls : null,
  };
}

export default function DashboardPage() {
  const [channels, setChannels] = useState<Channel[]>([]);
  // Single-channel view: the org's first channel (Hyundai has just one).
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [agentStats, setAgentStats] = useState<AgentStats[]>([]);
  const [statsLoading, setStatsLoading] = useState(false);

  useEffect(() => {
    listChannels()
      .then((data) => {
        setChannels(data);
        setSelectedId(data.length > 0 ? data[0].id : null);
        setLoading(false);
      })
      .catch((e) => {
        setError(e instanceof Error ? e.message : "Failed to load channels");
        setLoading(false);
      });
  }, []);

  useEffect(() => {
    if (selectedId === null) {
      setAgentStats([]);
      return;
    }
    let cancelled = false;
    setStatsLoading(true);
    listProcessAgents(selectedId)
      .then((agents) =>
        Promise.all(
          agents.map((agent) =>
            Promise.all([
              getProcessAgentStats(agent.id),
              // Best-effort: an agent whose calls fail to load just contributes none.
              getProcessAgentCalls(agent.id).catch(() => [] as CallRow[]),
            ]).then(([stats, calls]) => ({ agent, stats, calls })),
          ),
        ),
      )
      .then((all) => {
        if (cancelled) return;
        setAgentStats(all);
        setStatsLoading(false);
      })
      .catch((e) => {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : "Failed to load channel stats");
        setStatsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedId]);

  const overview = aggregateStats(agentStats.map((a) => a.stats));
  const show = (value: string) => (statsLoading ? "…" : value);

  // Every call in the selected channel, newest first, test calls left out.
  // Plus frontend-only sample calls for dealers that have none yet (lib/demoCalls.ts).
  const channelRows = useMemo(() => {
    const real = agentStats.flatMap((a) => a.calls.filter((row) => !isTestCall(row)));
    return [...real, ...demoCallsFor(real)].sort((a, b) => b.created_at.localeCompare(a.created_at));
  }, [agentStats]);

  return (
    <div className="space-y-6">
      {error && <ErrorAlert message={error} />}

      {loading && (
        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-28 rounded-xl" />
          ))}
        </div>
      )}

      {/* Empty state — no channels yet */}
      {!loading && !error && channels.length === 0 && (
        <EmptyState
          icon={Network}
          title="No channels yet"
          description="Create a channel to start building process agents."
          action={
            <Button asChild>
              <Link href="/channels">
                <Plus /> Add Channel
              </Link>
            </Button>
          }
        />
      )}

      {/* Main content — only once channels exist */}
      {!loading && !error && channels.length > 0 && (
        <>
          {/* Primary KPI row */}
          <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
            <KpiCard label="Total Calls" value={show(String(overview.calls))} icon={Phone} tone="blue" />
            <KpiCard label="Connected" value={show(String(overview.connected))} icon={PhoneCall} tone="green" />
            <KpiCard
              label="Connect Rate"
              value={show(formatPercent(overview.connectRate))}
              hint="Connected ÷ total calls"
              icon={Target}
              tone="purple"
            />
            <KpiCard
              label="Avg. Duration"
              value={show(formatDuration(overview.avgDurationSeconds))}
              hint="Across connected calls"
              icon={Clock}
              tone="orange"
            />
          </div>

          <DealerCallsCard key={selectedId} rows={channelRows} loading={statsLoading} />
        </>
      )}
    </div>
  );
}
