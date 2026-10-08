"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { getChannel, getProcessAgentStats } from "@/lib/telehubApi";
import type { ChannelDetail, ChannelNestedProcessAgent, ProcessAgentStats } from "@/lib/types";
import { Card } from "@/components/Card";
import { StatusBadge } from "@/components/StatusBadge";

// Process Agent `status` values (draft/active/…) aren't part of the shared
// lead-status vocabulary in lib/domainConfig.ts, so StatusBadge can't color
// them meaningfully (it'd fall back to grey for both), so this page keeps a
// component-local vocab that doesn't belong in domainConfig.
type Tone = "ok" | "warn" | "bad" | "muted";

const TONE_CLASSES: Record<Tone, string> = {
  ok: "bg-ok/10 text-ok border border-ok/20",
  warn: "bg-warn/10 text-warn border border-warn/20",
  bad: "bg-bad/10 text-bad border border-bad/20",
  muted: "bg-surface-container text-text-muted border border-border",
};

function processStatusTone(status: string): Tone {
  const s = status.toLowerCase();
  if (s === "active" || s === "published" || s === "live") return "ok";
  if (s === "draft") return "warn";
  if (s === "archived" || s === "disabled" || s === "paused") return "bad";
  return "muted";
}

function ProcessStatusPill({ status }: { status: string }) {
  return (
    <span className={`px-2 py-0.5 rounded-full text-xs font-medium capitalize ${TONE_CLASSES[processStatusTone(status)]}`}>
      {status}
    </span>
  );
}

function ActiveDot({ active }: { active: boolean }) {
  return (
    <span
      className={`inline-block w-2 h-2 rounded-full ${active ? "bg-ok" : "bg-bad"}`}
      title={active ? "Active" : "Inactive"}
    />
  );
}

function formatSeconds(seconds: number | null): string {
  if (seconds === null) return "—";
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

function StatPill({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex flex-col">
      <span className="text-[10px] uppercase tracking-wide text-text-muted">{label}</span>
      <span className="text-sm font-semibold text-on-surface">{value}</span>
    </div>
  );
}

function SkeletonCard() {
  return (
    <div className="bg-white border border-gray-100 rounded-xl p-5 animate-pulse">
      <div className="h-4 bg-gray-200 rounded w-2/3 mb-3" />
      <div className="h-3 bg-gray-100 rounded w-1/4 mb-4" />
      <div className="h-3 bg-gray-100 rounded w-1/3" />
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

  // Loading state
  if (loading) {
    return (
      <div className="space-y-6">
        <div className="animate-pulse space-y-2">
          <div className="h-3 bg-gray-100 rounded w-24" />
          <div className="h-6 bg-gray-200 rounded w-64" />
          <div className="h-3 bg-gray-100 rounded w-96" />
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {[1, 2, 3].map((i) => (
            <SkeletonCard key={i} />
          ))}
        </div>
      </div>
    );
  }

  // Error state (e.g. channel not found)
  if (error || !channel) {
    return (
      <div className="flex flex-col items-center justify-center py-24 text-center">
        <p className="text-sm font-semibold text-gray-800 mb-1">Channel not found</p>
        <p className="text-xs text-text-muted mb-4 max-w-sm">
          This channel may have been deleted, or the link you followed is incorrect.
          {error ? ` (${error})` : ""}
        </p>
        <Link href="/channels" className="text-primary text-sm font-medium hover:underline">
          ← Back to Channels
        </Link>
      </div>
    );
  }

  const processAgents: ChannelNestedProcessAgent[] = channel.process_agents ?? [];

  return (
    <div className="space-y-6">
      {/* Back link */}
      <Link href="/channels" className="text-xs text-text-muted hover:text-primary transition-colors">
        ← Back to Channels
      </Link>

      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <h1 className="text-lg font-semibold text-gray-800">{channel.name}</h1>
            <StatusBadge status={channel.is_active ? "active" : "inactive"} />
          </div>
          {channel.description && (
            <p className="text-sm text-text-muted mt-1 max-w-2xl">{channel.description}</p>
          )}
        </div>
        <Link
          href={`/process-agents/new?channel=${channel.id}`}
          className="shrink-0 flex items-center gap-1.5 px-4 py-2 rounded-lg bg-primary text-on-primary text-sm font-medium hover:bg-primary-container transition-colors"
        >
          <span className="text-base leading-none">+</span>
          Add Agent
        </Link>
      </div>

      {/* Empty state */}
      {processAgents.length === 0 && (
        <div className="flex flex-col items-center justify-center py-20 text-center border border-dashed border-border rounded-xl">
          <p className="text-gray-600 text-sm font-medium mb-1">This channel has no agents yet</p>
          <p className="text-xs text-text-muted mb-4 max-w-md">
            e.g. &ldquo;Free Service 1&rdquo;, &ldquo;Test Drive&rdquo;, &ldquo;Insurance Renewal&rdquo;
          </p>
          <Link
            href={`/process-agents/new?channel=${channel.id}`}
            className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-primary text-on-primary text-sm font-medium hover:bg-primary-container transition-colors"
          >
            <span className="text-base leading-none">+</span>
            Add Agent
          </Link>
        </div>
      )}

      {/* Process Agent grid */}
      {processAgents.length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {processAgents.map((pa) => {
            const stats = statsByAgent[pa.id];
            return (
              <Link key={pa.id} href={`/process-agents/${pa.id}`}>
                <Card className="p-5 hover:shadow-md hover:border-gray-200 transition-all cursor-pointer h-full">
                  <div className="flex items-start justify-between gap-2 mb-2">
                    <p className="text-sm font-semibold text-gray-800 truncate">{pa.name}</p>
                    <ActiveDot active={pa.is_active} />
                  </div>
                  <div className="flex items-center gap-2 mb-3">
                    <ProcessStatusPill status={pa.status} />
                    <span className="text-xs text-text-muted">v{pa.version}</span>
                  </div>
                  <div className="grid grid-cols-3 gap-2 pt-3 border-t border-gray-100">
                    <StatPill label="Calls" value={stats ? stats.calls : "—"} />
                    <StatPill label="Connected" value={stats ? stats.connected : "—"} />
                    <StatPill label="Avg" value={stats ? formatSeconds(stats.avg_duration_seconds) : "—"} />
                  </div>
                </Card>
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}
