"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  Mic,
  ArrowRight,
  Phone,
  PhoneCall,
  Target,
  Clock,
  Star,
  Flame,
  CalendarClock,
  ChartPie,
  Network,
  Plus,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { KpiCard, MiniStat } from "@/components/common/KpiCard";
import { EmptyState } from "@/components/common/EmptyState";
import { ErrorAlert } from "@/components/common/ErrorAlert";
import { ChannelIconTile } from "@/components/common/ChannelIcon";
import { listChannels, listProcessAgents, getProcessAgentStats, listVoiceBots } from "@/lib/telehubApi";
import { formatDuration, formatPercent, formatScore } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { Channel, ProcessAgentStats, ProcessAgentSummary } from "@/lib/types";

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
  connectRate: number | null; // connected / calls
}

interface AgentStats {
  agent: ProcessAgentSummary;
  stats: ProcessAgentStats;
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
    connectRate: calls > 0 ? connected / calls : null,
  };
}

// Donut segment colours, cycled when a channel has more agents than entries.
const SEGMENT_COLORS = ["#2563eb", "#10b981", "#f59e0b", "#8b5cf6", "#ec4899", "#14b8a6", "#64748b"];

export default function DashboardPage() {
  const [channels, setChannels] = useState<Channel[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [voiceBotCount, setVoiceBotCount] = useState<number | null>(null);
  const [agentStats, setAgentStats] = useState<AgentStats[]>([]);
  const [statsLoading, setStatsLoading] = useState(false);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);

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
    // The hero banner just falls back to its generic copy if this fails.
    listVoiceBots()
      .then((bots) => setVoiceBotCount(bots.length))
      .catch(() => setVoiceBotCount(null));
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
        Promise.all(agents.map((agent) => getProcessAgentStats(agent.id).then((stats) => ({ agent, stats })))),
      )
      .then((all) => {
        if (cancelled) return;
        setAgentStats(all);
        setUpdatedAt(new Date());
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

  return (
    <div className="space-y-6">
      <HeroBanner voiceBotCount={voiceBotCount} />

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
          {/* Channel selector + last refresh */}
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2 overflow-x-auto pb-1 min-w-0">
              {channels.map((d) => (
                <button
                  key={d.id}
                  onClick={() => setSelectedId(d.id)}
                  className={cn(
                    "shrink-0 inline-flex items-center gap-2 pl-1.5 pr-4 py-1.5 rounded-full text-sm font-medium transition-colors border",
                    selectedId === d.id
                      ? "bg-primary text-primary-foreground border-primary"
                      : "bg-card text-foreground border-border hover:bg-accent",
                  )}
                >
                  <ChannelIconTile icon={d.icon} color={selectedId === d.id ? "#ffffff" : d.color} size="sm" />
                  {d.name}
                </button>
              ))}
            </div>
            {updatedAt && (
              <p className="text-xs text-muted-foreground shrink-0">
                Last updated{" "}
                {updatedAt.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" })}
              </p>
            )}
          </div>

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

          {/* Calls by process agent + secondary stats */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            <AgentBreakdownCard rows={agentStats} loading={statsLoading} />
            <div className="grid grid-cols-1 sm:grid-cols-3 lg:grid-cols-1 gap-4">
              <MiniStat label="QA Score" value={show(formatScore(overview.qaScore))} icon={Star} />
              <MiniStat label="Hot Leads" value={show(String(overview.hotLeads))} icon={Flame} />
              <MiniStat label="Callback Due" value={show(String(overview.callbackRequests))} icon={CalendarClock} />
            </div>
          </div>
        </>
      )}
    </div>
  );
}

// ── Hero banner ─────────────────────────────────────────────────────────────

function HeroBanner({ voiceBotCount }: { voiceBotCount: number | null }) {
  const hasBots = voiceBotCount !== null && voiceBotCount > 0;
  const title = voiceBotCount === 0 ? "Set up your first Voicebot" : "Your Voicebots are Live";
  const subtitle = hasBots
    ? `${voiceBotCount} voicebot${voiceBotCount === 1 ? "" : "s"} configured — handling leads, answering questions, and taking action automatically.`
    : "Handle leads, answer questions, and take action — automatically.";

  return (
    <section className="relative overflow-hidden rounded-2xl border border-blue-100 bg-gradient-to-r from-blue-50 via-indigo-50 to-violet-100 p-6 sm:p-8">
      <HeroWaves className="absolute inset-y-0 right-0 h-full w-2/3 pointer-events-none" />
      <div className="relative flex items-center gap-6">
        <div className="hidden sm:flex w-20 h-20 shrink-0 rounded-full bg-primary items-center justify-center shadow-lg shadow-blue-600/25">
          <Mic className="w-9 h-9 text-primary-foreground" />
        </div>
        <div className="min-w-0">
          <h1 className="text-xl font-bold text-foreground">{title}</h1>
          <p className="text-sm text-muted-foreground mt-1">{subtitle}</p>
          <Button asChild className="mt-4">
            <Link href="/bots">
              View Voicebots <ArrowRight />
            </Link>
          </Button>
        </div>
      </div>
    </section>
  );
}

// Decorative soft hills + audio waveform, drawn inline so there's no image asset.
function HeroWaves({ className = "" }: { className?: string }) {
  const bars = [4, 7, 10, 14, 9, 18, 26, 34, 22, 40, 56, 30, 20, 34, 14, 10, 7, 5, 4];
  const barGap = 9;
  const startX = 380 - ((bars.length - 1) * barGap) / 2;
  return (
    <svg viewBox="0 0 600 200" preserveAspectRatio="xMidYMid slice" className={className} aria-hidden="true">
      <defs>
        <linearGradient id="hero-wave-bars" x1="0" x2="1" y1="0" y2="0">
          <stop offset="0" stopColor="#93c5fd" />
          <stop offset="0.5" stopColor="#4f46e5" />
          <stop offset="1" stopColor="#c4b5fd" />
        </linearGradient>
      </defs>
      <path d="M0 200 C120 120 220 90 330 130 C430 165 500 70 600 90 L600 200 Z" fill="#c7d2fe" opacity="0.35" />
      <path d="M0 200 C150 150 260 160 360 170 C460 180 520 130 600 140 L600 200 Z" fill="#a5b4fc" opacity="0.25" />
      {bars.map((h, i) => (
        <rect
          key={i}
          x={startX + i * barGap - 2}
          y={90 - h / 2}
          width={4}
          height={h}
          rx={2}
          fill="url(#hero-wave-bars)"
        />
      ))}
    </svg>
  );
}

// ── Calls by process agent (donut) ──────────────────────────────────────────

function AgentBreakdownCard({ rows, loading }: { rows: AgentStats[]; loading: boolean }) {
  const total = rows.reduce((sum, r) => sum + r.stats.calls, 0);
  const segments = rows.map((r, i) => ({
    id: r.agent.id,
    name: r.agent.name,
    calls: r.stats.calls,
    share: total > 0 ? r.stats.calls / total : 0,
    color: SEGMENT_COLORS[i % SEGMENT_COLORS.length],
  }));

  return (
    <Card className="lg:col-span-2 gap-4">
      <CardHeader className="flex flex-row items-start gap-3">
        <div className="w-10 h-10 shrink-0 rounded-lg bg-accent flex items-center justify-center">
          <ChartPie className="w-5 h-5 text-primary" />
        </div>
        <div className="space-y-1">
          <CardTitle>Calls by Process Agent</CardTitle>
          <CardDescription>Where this channel&apos;s calls are coming from</CardDescription>
        </div>
      </CardHeader>
      <CardContent>
        {loading ? (
          <div className="flex items-center gap-8">
            <Skeleton className="w-40 h-40 rounded-full" />
            <div className="flex-1 space-y-3">
              <Skeleton className="h-4 w-3/4" />
              <Skeleton className="h-4 w-1/2" />
            </div>
          </div>
        ) : rows.length === 0 ? (
          <p className="text-sm text-muted-foreground">No process agents in this channel yet.</p>
        ) : (
          <div className="flex flex-col sm:flex-row items-center gap-8">
            <Donut segments={segments} total={total} />
            <ul className="flex-1 w-full space-y-3 min-w-0">
              {segments.map((s) => (
                <li key={s.id} className="flex items-center gap-3 text-sm">
                  <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ backgroundColor: s.color }} />
                  <Link href={`/process-agents/${s.id}`} className="flex-1 truncate text-foreground hover:text-primary">
                    {s.name}
                  </Link>
                  <span className="w-12 text-right font-semibold text-foreground tabular-nums">{s.calls}</span>
                  <span className="w-12 text-right text-muted-foreground tabular-nums">
                    {formatPercent(total > 0 ? s.share : null)}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function Donut({
  segments,
  total,
}: {
  segments: { id: number; share: number; color: string }[];
  total: number;
}) {
  const radius = 42;
  const circumference = 2 * Math.PI * radius;
  // Each arc starts where the previous one ended.
  const arcs = segments
    .filter((s) => s.share > 0)
    .reduce<{ id: number; color: string; length: number; start: number }[]>((acc, s) => {
      const start = acc.length > 0 ? acc[acc.length - 1].start + acc[acc.length - 1].length : 0;
      return [...acc, { id: s.id, color: s.color, length: s.share * circumference, start }];
    }, []);

  return (
    <div className="relative w-40 h-40 shrink-0">
      <svg viewBox="0 0 100 100" className="w-full h-full -rotate-90" aria-hidden="true">
        <circle cx="50" cy="50" r={radius} fill="none" stroke="var(--color-muted)" strokeWidth="12" />
        {total > 0 &&
          arcs.map((a) => (
            <circle
              key={a.id}
              cx="50"
              cy="50"
              r={radius}
              fill="none"
              stroke={a.color}
              strokeWidth="12"
              strokeDasharray={`${a.length} ${circumference - a.length}`}
              strokeDashoffset={-a.start}
            />
          ))}
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="text-2xl font-bold text-foreground">{total}</span>
        <span className="text-xs text-muted-foreground">Total Calls</span>
      </div>
    </div>
  );
}
