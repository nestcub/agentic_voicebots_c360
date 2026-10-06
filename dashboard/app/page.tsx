"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Card, CardHeader } from "@/components/Card";
import { listChannels, listProcessAgents, getProcessAgentStats } from "@/lib/telehubApi";
import type { Channel, ProcessAgentStats } from "@/lib/types";

// Aggregated across every ProcessAgent in the selected channel — each field
// stays null (renders "—") when no process agent contributed any data for
// it, same fail-open convention as ProcessAgentStats itself.
interface ChannelOverview {
  calls: number;
  connected: number;
  avgDurationSeconds: number | null;
  qaScore: number | null;
  hotLeads: number;
  callbackRequests: number;
  conversion: number | null; // connected / calls
}

function aggregateStats(stats: ProcessAgentStats[]): ChannelOverview {
  const calls = stats.reduce((sum, s) => sum + s.calls, 0);
  const connected = stats.reduce((sum, s) => sum + s.connected, 0);
  const hotLeads = stats.reduce((sum, s) => sum + s.hot_leads, 0);
  const callbackRequests = stats.reduce((sum, s) => sum + s.callback_requests, 0);

  // Weight per-agent averages by their own connected/scored counts so one
  // low-volume agent doesn't skew the channel-wide average as much as one
  // that's actually handled most of the calls.
  const durationWeighted = stats.reduce(
    (acc, s) => (s.avg_duration_seconds !== null ? acc + s.avg_duration_seconds * s.connected : acc),
    0,
  );
  const avgDurationSeconds = connected > 0 && durationWeighted > 0 ? durationWeighted / connected : null;

  const qaWeighted = stats.reduce((acc, s) => (s.qa_score !== null ? acc + s.qa_score * s.calls : acc), 0);
  const qaScore = calls > 0 && qaWeighted > 0 ? qaWeighted / calls : null;

  return {
    calls,
    connected,
    avgDurationSeconds,
    qaScore,
    hotLeads,
    callbackRequests,
    conversion: calls > 0 ? connected / calls : null,
  };
}

function formatDuration(seconds: number | null): string {
  if (seconds === null) return "—";
  const mins = Math.floor(seconds / 60);
  const secs = Math.round(seconds % 60);
  return `${mins}:${secs.toString().padStart(2, "0")}`;
}

function formatPercent(ratio: number | null): string {
  if (ratio === null) return "—";
  return `${Math.round(ratio * 100)}%`;
}

function formatScore(score: number | null): string {
  if (score === null) return "—";
  return score.toFixed(1);
}

function kpiTiles(overview: ChannelOverview): { label: string; value: string }[] {
  return [
    { label: "Calls", value: String(overview.calls) },
    { label: "Connected", value: String(overview.connected) },
    { label: "Conversion", value: formatPercent(overview.conversion) },
    { label: "Avg Duration", value: formatDuration(overview.avgDurationSeconds) },
    { label: "QA Score", value: formatScore(overview.qaScore) },
    { label: "Hot Leads", value: String(overview.hotLeads) },
    { label: "Callback Due", value: String(overview.callbackRequests) },
  ];
}

export default function DashboardPage() {
  const [channels, setChannels] = useState<Channel[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [overview, setOverview] = useState<ChannelOverview | null>(null);
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
      setOverview(null);
      return;
    }
    let cancelled = false;
    setStatsLoading(true);
    listProcessAgents(selectedId)
      .then((agents) => Promise.all(agents.map((a) => getProcessAgentStats(a.id))))
      .then((allStats) => {
        if (cancelled) return;
        setOverview(aggregateStats(allStats));
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

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-lg font-semibold text-on-surface">Dashboard</h1>
        <p className="text-xs text-text-muted mt-0.5">Channel-level overview</p>
      </div>

      {/* Error banner */}
      {error && (
        <div className="text-sm text-bad bg-bad/10 border border-bad/30 rounded-lg px-4 py-2">
          {error}
        </div>
      )}

      {/* Loading */}
      {loading && <p className="text-sm text-text-muted">Loading…</p>}

      {/* Empty state — no channels yet */}
      {!loading && !error && channels.length === 0 && (
        <Card className="p-10 flex flex-col items-center justify-center text-center">
          <p className="text-sm text-text-muted mb-3">
            No channels yet. Create one to start building process agents.
          </p>
          <Link
            href="/channels"
            className="px-4 py-2 rounded-lg bg-primary text-on-primary text-sm font-medium hover:bg-primary-container transition-colors"
          >
            + Add Channel
          </Link>
        </Card>
      )}

      {/* Main content — only once channels exist */}
      {!loading && !error && channels.length > 0 && (
        <>
          {/* Channel selector */}
          <div className="flex items-center gap-2 overflow-x-auto pb-1">
            {channels.map((d) => (
              <button
                key={d.id}
                onClick={() => setSelectedId(d.id)}
                className={`shrink-0 px-4 py-2 rounded-full text-sm font-medium transition-colors border ${
                  selectedId === d.id
                    ? "bg-primary text-on-primary border-primary"
                    : "bg-surface text-on-surface border-border hover:bg-surface-container"
                }`}
              >
                {d.icon ? `${d.icon} ` : ""}
                {d.name}
              </button>
            ))}
          </div>

          {/* KPI row */}
          <div>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
              {kpiTiles(overview ?? aggregateStats([])).map((tile) => (
                <Card key={tile.label} className="p-5">
                  <p className="text-xs font-medium text-text-muted uppercase tracking-wide">
                    {tile.label}
                  </p>
                  <p className="text-3xl font-bold text-on-surface mt-1">
                    {statsLoading ? "…" : tile.value}
                  </p>
                </Card>
              ))}
            </div>
            <p className="text-xs text-text-muted mt-2">
              Aggregated across every process in this channel. Live metrics appear once your processes
              start running.
            </p>
          </div>

          {/* AI Recommendations placeholder */}
          <Card className="p-0 overflow-hidden">
            <CardHeader title="AI Recommendations" />
            <div className="px-5 pb-5">
              <p className="text-sm text-text-muted">
                Recommendations will appear here once channels have active processes.
              </p>
            </div>
          </Card>
        </>
      )}
    </div>
  );
}
