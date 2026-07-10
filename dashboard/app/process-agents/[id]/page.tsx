"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { Card, CardHeader } from "@/components/Card";
import { StatusBadge } from "@/components/StatusBadge";
import { StatCard } from "@/components/StatCard";
import {
  getProcessAgent,
  getProcessAgentJourney,
  getProcessAgentExecutions,
  getProcessAgentQaResults,
  updateProcessAgent,
} from "@/lib/telehubApi";
import type {
  ProcessAgentDetail,
  JourneyNode,
  JourneyEdge,
  Execution,
  QaResult,
} from "@/lib/types";

type TabKey = "overview" | "journey" | "runs" | "qa" | "settings";

const TABS: { key: TabKey; label: string }[] = [
  { key: "overview", label: "Overview" },
  { key: "journey", label: "Journey" },
  { key: "runs", label: "Runs" },
  { key: "qa", label: "QA" },
  { key: "settings", label: "Settings" },
];

const NODE_TYPE_STYLE: Record<string, { dot: string; text: string }> = {
  trigger: { dot: "bg-accent", text: "text-accent" },
  logic: { dot: "bg-text-muted", text: "text-text-muted" },
  communication: { dot: "bg-primary", text: "text-primary" },
  retry: { dot: "bg-warn", text: "text-warn" },
  routing: { dot: "bg-primary-container", text: "text-primary-container" },
  integration: { dot: "bg-ok", text: "text-ok" },
  qa: { dot: "bg-accent", text: "text-accent" },
  output: { dot: "bg-ok", text: "text-ok" },
};

function nodeStyle(type: string) {
  return NODE_TYPE_STYLE[type] ?? { dot: "bg-text-muted", text: "text-text-muted" };
}

function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

function formatDuration(seconds: number | null): string {
  if (seconds === null || seconds === undefined) return "—";
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

function errorMessage(e: unknown, fallback: string): string {
  return e instanceof Error ? e.message : fallback;
}

export default function ProcessAgentDetailPage() {
  const params = useParams<{ id: string }>();
  const rawId = params?.id;
  const id = Number(Array.isArray(rawId) ? rawId[0] : rawId);
  const validId = Number.isFinite(id);

  const [agent, setAgent] = useState<ProcessAgentDetail | null>(null);
  const [agentLoading, setAgentLoading] = useState(true);
  const [agentError, setAgentError] = useState<string | null>(null);
  const [notFound, setNotFound] = useState(false);

  const [tab, setTab] = useState<TabKey>("overview");

  // Journey tab state
  const [journeyData, setJourneyData] = useState<{ nodes: JourneyNode[]; edges: JourneyEdge[] } | null>(null);
  const [journeyLoading, setJourneyLoading] = useState(false);
  const [journeyError, setJourneyError] = useState<string | null>(null);
  const [journeyFetched, setJourneyFetched] = useState(false);

  // Runs tab state
  const [executions, setExecutions] = useState<Execution[] | null>(null);
  const [executionsLoading, setExecutionsLoading] = useState(false);
  const [executionsError, setExecutionsError] = useState<string | null>(null);
  const [executionsFetched, setExecutionsFetched] = useState(false);

  // QA tab state
  const [qaResults, setQaResults] = useState<QaResult[] | null>(null);
  const [qaLoading, setQaLoading] = useState(false);
  const [qaError, setQaError] = useState<string | null>(null);
  const [qaFetched, setQaFetched] = useState(false);

  // Settings tab: active toggle
  const [togglingActive, setTogglingActive] = useState(false);
  const [toggleError, setToggleError] = useState<string | null>(null);

  const loadAgent = useCallback(() => {
    if (!validId) {
      setAgentLoading(false);
      setNotFound(true);
      return;
    }
    setAgentLoading(true);
    setAgentError(null);
    setNotFound(false);
    getProcessAgent(id)
      .then((data) => {
        setAgent(data);
        setAgentLoading(false);
      })
      .catch((e: unknown) => {
        const message = errorMessage(e, "Failed to load process agent");
        if (message.includes("404")) {
          setNotFound(true);
        } else {
          setAgentError(message);
        }
        setAgentLoading(false);
      });
  }, [id, validId]);

  useEffect(() => {
    loadAgent();
  }, [loadAgent]);

  // Lazy fetch: Journey
  useEffect(() => {
    if (!validId || tab !== "journey" || journeyFetched) return;
    let cancelled = false;
    setJourneyLoading(true);
    setJourneyError(null);
    getProcessAgentJourney(id)
      .then((data) => {
        if (cancelled) return;
        setJourneyData(data);
        setJourneyFetched(true);
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        setJourneyError(errorMessage(e, "Failed to load journey"));
        setJourneyFetched(true);
      })
      .finally(() => {
        if (!cancelled) setJourneyLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [validId, tab, journeyFetched, id]);

  // Lazy fetch: Runs
  useEffect(() => {
    if (!validId || tab !== "runs" || executionsFetched) return;
    let cancelled = false;
    setExecutionsLoading(true);
    setExecutionsError(null);
    getProcessAgentExecutions(id)
      .then((data) => {
        if (cancelled) return;
        setExecutions(data);
        setExecutionsFetched(true);
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        setExecutionsError(errorMessage(e, "Failed to load executions"));
        setExecutionsFetched(true);
      })
      .finally(() => {
        if (!cancelled) setExecutionsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [validId, tab, executionsFetched, id]);

  // Lazy fetch: QA
  useEffect(() => {
    if (!validId || tab !== "qa" || qaFetched) return;
    let cancelled = false;
    setQaLoading(true);
    setQaError(null);
    getProcessAgentQaResults(id)
      .then((data) => {
        if (cancelled) return;
        setQaResults(data);
        setQaFetched(true);
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        setQaError(errorMessage(e, "Failed to load QA results"));
        setQaFetched(true);
      })
      .finally(() => {
        if (!cancelled) setQaLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [validId, tab, qaFetched, id]);

  async function handleToggleActive() {
    if (!agent) return;
    setTogglingActive(true);
    setToggleError(null);
    try {
      await updateProcessAgent(agent.id, { is_active: !agent.is_active });
      loadAgent();
    } catch (e) {
      setToggleError(errorMessage(e, "Failed to update status"));
    } finally {
      setTogglingActive(false);
    }
  }

  if (!validId || notFound) {
    return (
      <div className="flex flex-col items-center justify-center py-24 text-center">
        <p className="text-lg font-semibold text-on-surface mb-1">Process not found</p>
        <p className="text-sm text-text-muted mb-4">
          This process agent doesn&apos;t exist or may have been removed.
        </p>
        <Link href="/departments" className="text-sm text-primary hover:underline">
          ← Back to Departments
        </Link>
      </div>
    );
  }

  if (agentLoading) {
    return (
      <div className="space-y-6">
        <div className="h-6 w-64 bg-surface-container rounded animate-pulse" />
        <div className="h-4 w-40 bg-surface-container rounded animate-pulse" />
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="h-24 bg-surface-container rounded-xl animate-pulse" />
          ))}
        </div>
      </div>
    );
  }

  if (agentError || !agent) {
    return (
      <div className="space-y-3">
        <div className="text-sm text-bad bg-bad/10 border border-bad/30 rounded-lg px-4 py-3">
          {agentError ?? "Failed to load process agent."}
        </div>
        <button
          onClick={loadAgent}
          className="text-sm text-primary hover:underline"
        >
          Retry
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="space-y-1">
        <Link
          href={`/departments/${agent.department}`}
          className="text-xs text-text-muted hover:text-primary hover:underline"
        >
          ← {agent.department_name}
        </Link>
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-xl font-semibold text-on-surface">{agent.name}</h1>
          <StatusBadge status={agent.status} />
          <span className="text-xs text-text-muted">v{agent.version}</span>
          {!agent.is_active && (
            <span className="text-xs font-medium px-2 py-0.5 rounded-full bg-text-muted/15 text-text-muted">
              Inactive
            </span>
          )}
        </div>
        {agent.description && (
          <p className="text-sm text-text-muted max-w-2xl">{agent.description}</p>
        )}
      </div>

      {/* Tab bar */}
      <div className="border-b border-border flex gap-1 overflow-x-auto">
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`px-4 py-2 text-sm font-medium whitespace-nowrap border-b-2 -mb-px transition-colors ${
              tab === t.key
                ? "border-primary text-primary"
                : "border-transparent text-text-muted hover:text-on-surface"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      {tab === "overview" && <OverviewTab agent={agent} />}
      {tab === "journey" && (
        <JourneyTab
          data={journeyData}
          loading={journeyLoading}
          error={journeyError}
        />
      )}
      {tab === "runs" && (
        <RunsTab executions={executions} loading={executionsLoading} error={executionsError} />
      )}
      {tab === "qa" && (
        <QaTab qaResults={qaResults} loading={qaLoading} error={qaError} />
      )}
      {tab === "settings" && (
        <SettingsTab
          agent={agent}
          onToggleActive={handleToggleActive}
          toggling={togglingActive}
          toggleError={toggleError}
        />
      )}
    </div>
  );
}

// ── Overview ─────────────────────────────────────────────────────────────

function OverviewTab({ agent }: { agent: ProcessAgentDetail }) {
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
        <InfoCard label="Status" value={<StatusBadge status={agent.status} />} />
        <InfoCard label="Version" value={`v${agent.version}`} />
        <InfoCard label="Active" value={agent.is_active ? "Yes" : "No"} />
        <InfoCard
          label="Department"
          value={
            <Link href={`/departments/${agent.department}`} className="text-primary hover:underline">
              {agent.department_name}
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
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
          <StatCard label="Calls" value="—" />
          <StatCard label="Connected" value="—" />
          <StatCard label="Avg Duration" value="—" />
          <StatCard label="QA Score" value="—" />
          <StatCard label="Hot Leads" value="—" />
          <StatCard label="Callback Requests" value="—" />
        </div>
        <p className="text-xs text-text-muted mt-2">
          Populates once this process starts running calls.
        </p>
      </div>
    </div>
  );
}

function InfoCard({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <Card className="p-4">
      <p className="text-xs font-medium text-text-muted uppercase tracking-wide">{label}</p>
      <div className="mt-1 text-sm font-semibold text-on-surface">{value}</div>
    </Card>
  );
}

// ── Journey ──────────────────────────────────────────────────────────────

function JourneyTab({
  data,
  loading,
  error,
}: {
  data: { nodes: JourneyNode[]; edges: JourneyEdge[] } | null;
  loading: boolean;
  error: string | null;
}) {
  if (loading) {
    return (
      <div className="flex gap-4 overflow-x-auto pb-2">
        {[1, 2, 3, 4].map((i) => (
          <div key={i} className="h-28 w-40 shrink-0 bg-surface-container rounded-xl animate-pulse" />
        ))}
      </div>
    );
  }

  if (error) {
    return <div className="text-sm text-bad bg-bad/10 border border-bad/30 rounded-lg px-4 py-3">{error}</div>;
  }

  if (!data || data.nodes.length === 0) {
    return <p className="text-sm text-text-muted">No journey generated for this process yet.</p>;
  }

  // The graph branches (e.g. Completed fans out to 4 outcome nodes) and loops
  // (Retry/Callback back to Business Hours) — it's no longer a single chain, so
  // rendering can't just connect position-adjacent nodes 1:1. Instead: group nodes
  // into columns by position_x (stacking same-x nodes vertically by position_y),
  // and list each node's actual outgoing edges as chips underneath its card —
  // forward chips (target is in a later column) vs loop-back chips (target is in
  // the same or an earlier column, shown with a ↩ and dashed style).
  const nodesById = new Map(data.nodes.map((n) => [n.id, n]));
  const outgoingByNode = new Map<number, JourneyEdge[]>();
  for (const edge of data.edges) {
    const list = outgoingByNode.get(edge.source_node) ?? [];
    list.push(edge);
    outgoingByNode.set(edge.source_node, list);
  }

  const columnXs = [...new Set(data.nodes.map((n) => n.position_x))].sort((a, b) => a - b);
  const columns = columnXs.map((x) =>
    data.nodes.filter((n) => n.position_x === x).sort((a, b) => a.position_y - b.position_y)
  );

  return (
    <div className="space-y-2">
      <p className="text-xs text-text-muted">
        Read-only view — journeys are generated automatically. Editing is not available in V1. Dashed
        chips (↩) are loop-backs — e.g. Retry/Callback re-enter the flow at Business Hours.
      </p>
      <Card className="p-4 overflow-x-auto">
        <div className="flex items-start gap-6 min-w-max">
          {columns.map((column, colIdx) => (
            <div key={colIdx} className="flex flex-col gap-3">
              {column.map((node) => {
                const style = nodeStyle(node.node_template_type);
                const outgoing = outgoingByNode.get(node.id) ?? [];
                return (
                  <div key={node.id} className="w-48 shrink-0 rounded-lg border border-border bg-surface p-3">
                    <div className="flex items-center gap-2">
                      <span className={`w-2.5 h-2.5 rounded-full shrink-0 ${style.dot}`} />
                      <span className={`text-[11px] font-medium uppercase tracking-wide ${style.text}`}>
                        {node.node_template_type}
                      </span>
                    </div>
                    <p className="text-sm font-semibold text-on-surface mt-1 truncate" title={node.name}>
                      {node.name}
                    </p>
                    {!node.enabled && <span className="text-[10px] text-text-muted">disabled</span>}

                    {outgoing.length > 0 && (
                      <div className="flex flex-wrap gap-1 mt-2">
                        {outgoing.map((edge) => {
                          const target = nodesById.get(edge.target_node);
                          const isLoop = target ? target.position_x <= node.position_x : false;
                          return (
                            <span
                              key={edge.id}
                              title={edge.condition || undefined}
                              className={`text-[10px] px-1.5 py-0.5 rounded-full border whitespace-nowrap ${
                                isLoop
                                  ? "border-dashed border-accent text-accent"
                                  : "border-border text-text-muted"
                              }`}
                            >
                              {isLoop ? "↩ " : "→ "}
                              {target?.name ?? "?"}
                              {edge.condition ? ` (${edge.condition})` : ""}
                            </span>
                          );
                        })}
                      </div>
                    )}

                    <details className="mt-2">
                      <summary className="cursor-pointer text-[11px] text-primary select-none">
                        config
                      </summary>
                      <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap break-words bg-background rounded p-2 text-[10px] text-text-muted">
                        {JSON.stringify(node.config, null, 2)}
                      </pre>
                    </details>
                  </div>
                );
              })}
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}

// ── Runs ─────────────────────────────────────────────────────────────────

function RunsTab({
  executions,
  loading,
  error,
}: {
  executions: Execution[] | null;
  loading: boolean;
  error: string | null;
}) {
  if (loading) {
    return <div className="h-32 bg-surface-container rounded-xl animate-pulse" />;
  }
  if (error) {
    return <div className="text-sm text-bad bg-bad/10 border border-bad/30 rounded-lg px-4 py-3">{error}</div>;
  }
  if (!executions || executions.length === 0) {
    return (
      <Card className="p-8 text-center">
        <p className="text-sm text-text-muted">
          No executions yet — this process hasn&apos;t run any calls.
        </p>
      </Card>
    );
  }

  return (
    <Card className="p-0 overflow-hidden">
      <CardHeader title="Runs" hint={`${executions.length} execution${executions.length === 1 ? "" : "s"}`} />
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-text-muted uppercase tracking-wide border-t border-border">
              <th className="px-5 py-2 font-medium">Lead</th>
              <th className="px-5 py-2 font-medium">Status</th>
              <th className="px-5 py-2 font-medium">Started</th>
              <th className="px-5 py-2 font-medium">Duration</th>
              <th className="px-5 py-2 font-medium">Current Node</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {executions.map((ex) => (
              <tr key={ex.id}>
                <td className="px-5 py-2.5 text-on-surface">{ex.lead_id}</td>
                <td className="px-5 py-2.5">
                  <StatusBadge status={ex.status} />
                </td>
                <td className="px-5 py-2.5 text-text-muted">{formatDate(ex.started_at)}</td>
                <td className="px-5 py-2.5 text-text-muted">{formatDuration(ex.duration)}</td>
                <td className="px-5 py-2.5 text-text-muted">{ex.current_node || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

// ── QA ───────────────────────────────────────────────────────────────────

function QaTab({
  qaResults,
  loading,
  error,
}: {
  qaResults: QaResult[] | null;
  loading: boolean;
  error: string | null;
}) {
  if (loading) {
    return <div className="h-32 bg-surface-container rounded-xl animate-pulse" />;
  }
  if (error) {
    return <div className="text-sm text-bad bg-bad/10 border border-bad/30 rounded-lg px-4 py-3">{error}</div>;
  }
  if (!qaResults || qaResults.length === 0) {
    return (
      <Card className="p-8 text-center">
        <p className="text-sm text-text-muted">No QA results yet.</p>
      </Card>
    );
  }

  return (
    <Card className="p-0 overflow-hidden">
      <CardHeader title="QA Results" hint={`${qaResults.length} result${qaResults.length === 1 ? "" : "s"}`} />
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-text-muted uppercase tracking-wide border-t border-border">
              <th className="px-5 py-2 font-medium">Summary</th>
              <th className="px-5 py-2 font-medium">Sentiment</th>
              <th className="px-5 py-2 font-medium">Hot Lead</th>
              <th className="px-5 py-2 font-medium">Bot Failure</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {qaResults.map((qa) => (
              <tr key={qa.id}>
                <td className="px-5 py-2.5 text-on-surface max-w-xs truncate" title={qa.summary}>
                  {qa.summary || "—"}
                </td>
                <td className="px-5 py-2.5 text-text-muted">{qa.sentiment || "—"}</td>
                <td className="px-5 py-2.5">
                  {qa.hot_lead ? (
                    <span className="text-xs font-medium px-2 py-0.5 rounded-full bg-ok/15 text-ok">Yes</span>
                  ) : (
                    <span className="text-text-muted text-xs">No</span>
                  )}
                </td>
                <td className="px-5 py-2.5">
                  {qa.bot_failure ? (
                    <span className="text-xs font-medium px-2 py-0.5 rounded-full bg-bad/15 text-bad">Yes</span>
                  ) : (
                    <span className="text-text-muted text-xs">No</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

// ── Settings ─────────────────────────────────────────────────────────────

function SettingsTab({
  agent,
  onToggleActive,
  toggling,
  toggleError,
}: {
  agent: ProcessAgentDetail;
  onToggleActive: () => void;
  toggling: boolean;
  toggleError: string | null;
}) {
  return (
    <div className="space-y-6">
      <Card className="p-5 flex items-center justify-between">
        <div>
          <p className="text-sm font-semibold text-on-surface">Process status</p>
          <p className="text-xs text-text-muted mt-0.5">
            {agent.is_active ? "This process is active and can run." : "This process is inactive and won't run."}
          </p>
          {toggleError && <p className="text-xs text-bad mt-1">{toggleError}</p>}
        </div>
        <button
          onClick={onToggleActive}
          disabled={toggling}
          className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors disabled:opacity-60 ${
            agent.is_active
              ? "border border-border text-text-muted hover:bg-surface-container"
              : "bg-primary text-on-primary hover:bg-primary-container"
          }`}
        >
          {toggling ? "Saving…" : agent.is_active ? "Deactivate" : "Activate"}
        </button>
      </Card>

      <SettingsSection title="Lead Sources" hint={`${agent.lead_sources.length} configured`}>
        {agent.lead_sources.length === 0 && <EmptySection label="No lead sources configured." />}
        {agent.lead_sources.map((ls) => (
          <div key={ls.id} className="rounded-lg border border-border p-3">
            <p className="text-sm font-medium text-on-surface">{ls.type}</p>
            <pre className="mt-1 max-h-32 overflow-auto whitespace-pre-wrap break-words bg-background rounded p-2 text-[11px] text-text-muted">
              {JSON.stringify(ls.configuration, null, 2)}
            </pre>
          </div>
        ))}
      </SettingsSection>

      <SettingsSection title="Variables" hint={`${agent.variables.length} configured`}>
        {agent.variables.length === 0 && <EmptySection label="No variables configured." />}
        {agent.variables.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-text-muted uppercase tracking-wide">
                  <th className="py-1.5 pr-4 font-medium">Key</th>
                  <th className="py-1.5 pr-4 font-medium">Type</th>
                  <th className="py-1.5 pr-4 font-medium">Default</th>
                  <th className="py-1.5 pr-4 font-medium">Required</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {agent.variables.map((v) => (
                  <tr key={v.id}>
                    <td className="py-1.5 pr-4 text-on-surface font-mono text-xs">{v.key}</td>
                    <td className="py-1.5 pr-4 text-text-muted">{v.type}</td>
                    <td className="py-1.5 pr-4 text-text-muted">{v.default_value || "—"}</td>
                    <td className="py-1.5 pr-4 text-text-muted">{v.required ? "Yes" : "No"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </SettingsSection>

      <SettingsSection title="Webhooks" hint={`${agent.webhooks.length} configured`}>
        {agent.webhooks.length === 0 && <EmptySection label="No webhooks configured." />}
        {agent.webhooks.map((wh) => (
          <div key={wh.id} className="rounded-lg border border-border p-3">
            <div className="flex items-center justify-between gap-2">
              <p className="text-sm font-medium text-on-surface">{wh.name}</p>
              <span className="text-xs text-text-muted">{wh.status}</span>
            </div>
            {wh.public_url ? (
              <p className="text-xs text-on-surface mt-0.5 break-all font-mono">{wh.public_url}</p>
            ) : (
              <>
                <p className="text-xs text-text-muted mt-0.5 break-all font-mono">{wh.url}</p>
                <p className="text-[11px] text-text-muted mt-1">
                  No public URL — run <code className="font-mono">ngrok http 8000</code> locally to
                  get one for pasting into the voice platform.
                </p>
              </>
            )}
          </div>
        ))}
      </SettingsSection>

      <SettingsSection title="Integrations" hint={`${agent.integrations.length} configured`}>
        {agent.integrations.length === 0 && <EmptySection label="No integrations configured." />}
        {agent.integrations.map((it) => (
          <div key={it.id} className="rounded-lg border border-border p-3 flex items-center justify-between">
            <p className="text-sm font-medium text-on-surface">{it.integration_name}</p>
            <span className="text-xs text-text-muted">{it.integration_type}</span>
          </div>
        ))}
      </SettingsSection>
    </div>
  );
}

function SettingsSection({
  title,
  hint,
  children,
}: {
  title: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <Card className="p-5 space-y-3">
      <CardHeader title={title} hint={hint} />
      <div className="space-y-2">{children}</div>
    </Card>
  );
}

function EmptySection({ label }: { label: string }) {
  return <p className="text-sm text-text-muted">{label}</p>;
}
