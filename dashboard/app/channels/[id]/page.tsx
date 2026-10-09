"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { ArrowLeft, ArrowRight, Clock, Phone, PhoneCall, Plus, Target, Workflow } from "lucide-react";
import { getChannel, getProcessAgentStats } from "@/lib/telehubApi";
import type { ChannelDetail, ChannelNestedProcessAgent, ProcessAgentStats } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { PageHeader } from "@/components/common/PageHeader";
import { EmptyState } from "@/components/common/EmptyState";
import { KpiCard } from "@/components/common/KpiCard";
import { channelIcon, DEFAULT_CHANNEL_COLOR } from "@/components/common/ChannelIcon";
import { ActiveBadge, ProcessStatusBadge } from "@/components/StatusBadge";
import { formatDuration, formatPercent } from "@/lib/format";

function formatSeconds(seconds: number | null): string {
  if (seconds === null) return "—";
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

function StatPill({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex flex-col">
      <span className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</span>
      <span className="text-sm font-semibold text-foreground">{value}</span>
    </div>
  );
}

export default function ChannelDetailPage() {
  const params = useParams<{ id: string }>();
  const id = params?.id;

  const [channel, setChannel] = useState<ChannelDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Per-agent call stats — "data chosen during agent creation", shown right on
  // the channel page (services/telehub/apps/telehub/services/analytics_stats.py).
  const [statsByAgent, setStatsByAgent] = useState<Record<number, ProcessAgentStats>>({});

  useEffect(() => {
    if (!id) return;
    const numericId = Number(id);
    if (Number.isNaN(numericId)) {
      setError("Invalid channel id");
      setLoading(false);
      return;
    }

    let cancelled = false;
    setLoading(true);
    setError(null);

    getChannel(numericId)
      .then((data) => {
        if (cancelled) return;
        setChannel(data);
        setLoading(false);
      })
      .catch((e) => {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : "Failed to load channel");
        setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [id]);

  // Fetch each listed agent's call stats once the channel (and its agent list) loads.
  // Best-effort: a failed fetch for one agent just leaves it without stats (renders "—"),
  // never blocks the page.
  useEffect(() => {
    const agents = channel?.process_agents ?? [];
    if (agents.length === 0) return;
    let cancelled = false;
    Promise.all(
      agents.map((pa) =>
        getProcessAgentStats(pa.id)
          .then((stats) => [pa.id, stats] as const)
          .catch(() => null),
      ),
    ).then((results) => {
      if (cancelled) return;
      const next: Record<number, ProcessAgentStats> = {};
      for (const r of results) {
        if (r) next[r[0]] = r[1];
      }
      setStatsByAgent(next);
    });
    return () => {
      cancelled = true;
    };
  }, [channel]);

  if (loading) {
    return (
      <div className="space-y-6">
        <div className="space-y-3">
          <Skeleton className="h-4 w-40" />
          <div className="flex items-center gap-3">
            <Skeleton className="h-11 w-11 rounded-xl" />
            <Skeleton className="h-6 w-64" />
          </div>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-28 rounded-xl" />
          ))}
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-36 rounded-xl" />
          ))}
        </div>
      </div>
    );
  }

  // Error state (e.g. channel not found)
  if (error || !channel) {
    return (
      <EmptyState
        icon={Workflow}
        title="Channel not found"
        description={`This channel may have been deleted, or the link you followed is incorrect.${error ? ` (${error})` : ""}`}
        action={
          <Button variant="outline" asChild>
            <Link href="/channels">
              <ArrowLeft /> Back to Channels
            </Link>
          </Button>
        }
        className="py-24"
      />
    );
  }

  const processAgents: ChannelNestedProcessAgent[] = channel.process_agents ?? [];
  const allStats = Object.values(statsByAgent);
  const calls = allStats.reduce((sum, s) => sum + s.calls, 0);
  const connected = allStats.reduce((sum, s) => sum + s.connected, 0);
  // Weighted by connected calls, same as the Dashboard's channel overview.
  const durationWeighted = allStats.reduce(
    (acc, s) => (s.avg_duration_seconds !== null ? acc + s.avg_duration_seconds * s.connected : acc),
    0,
  );
  const avgDuration = connected > 0 && durationWeighted > 0 ? durationWeighted / connected : null;
  const statsReady = processAgents.length === 0 || allStats.length > 0;
  const show = (value: string) => (statsReady ? value : "…");

  const addAgentButton = (
    <Button asChild>
      <Link href={`/process-agents/new?channel=${channel.id}`}>
        <Plus /> Add Agent
      </Link>
    </Button>
  );

  return (
    <div className="space-y-6">
      <PageHeader
        breadcrumbs={[{ label: "Channels", href: "/channels" }, { label: channel.name }]}
        icon={channelIcon(channel.icon)}
        iconColor={channel.color || DEFAULT_CHANNEL_COLOR}
        title={channel.name}
        badges={<ActiveBadge active={channel.is_active} />}
        description={channel.description || undefined}
        actions={addAgentButton}
      />

      {processAgents.length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
          <KpiCard label="Total Calls" value={show(String(calls))} icon={Phone} tone="blue" />
          <KpiCard label="Connected" value={show(String(connected))} icon={PhoneCall} tone="green" />
          <KpiCard
            label="Connect Rate"
            value={show(formatPercent(calls > 0 ? connected / calls : null))}
            hint="Connected ÷ total calls"
            icon={Target}
            tone="purple"
          />
          <KpiCard
            label="Avg. Duration"
            value={show(formatDuration(avgDuration))}
            hint="Across connected calls"
            icon={Clock}
            tone="orange"
          />
        </div>
      )}

      {processAgents.length === 0 && (
        <EmptyState
          icon={Workflow}
          title="This channel has no agents yet"
          description={<>e.g. &ldquo;Free Service 1&rdquo;, &ldquo;Test Drive&rdquo;, &ldquo;Insurance Renewal&rdquo;</>}
          action={addAgentButton}
        />
      )}

      {processAgents.length > 0 && (
        <div className="space-y-3">
          <h2 className="text-sm font-semibold text-foreground">Process Agents</h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {processAgents.map((pa) => {
              const stats = statsByAgent[pa.id];
              return (
                <Link key={pa.id} href={`/process-agents/${pa.id}`} className="group">
                  <Card className="h-full gap-0 p-5 transition-all group-hover:shadow-md group-hover:-translate-y-0.5">
                    <div className="flex items-start justify-between gap-2 mb-2">
                      <div className="flex items-center gap-3 min-w-0">
                        <span className="w-9 h-9 shrink-0 rounded-lg bg-accent text-primary flex items-center justify-center">
                          <Workflow className="w-4 h-4" />
                        </span>
                        <p className="text-sm font-semibold text-foreground truncate">{pa.name}</p>
                      </div>
                      <ArrowRight className="w-4 h-4 mt-2.5 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5 group-hover:text-primary" />
                    </div>
                    <div className="flex flex-wrap items-center gap-2 mb-4">
                      <ProcessStatusBadge status={pa.status} />
                      <ActiveBadge active={pa.is_active} />
                      <span className="text-xs text-muted-foreground">v{pa.version}</span>
                    </div>
                    <div className="grid grid-cols-3 gap-2 pt-3 mt-auto border-t border-border">
                      <StatPill label="Calls" value={stats ? stats.calls : "—"} />
                      <StatPill label="Connected" value={stats ? stats.connected : "—"} />
                      <StatPill label="Avg" value={stats ? formatSeconds(stats.avg_duration_seconds) : "—"} />
                    </div>
                  </Card>
                </Link>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
