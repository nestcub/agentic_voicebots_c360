import { useState } from "react";
import { Card, CardHeader } from "@/components/Card";
import { StatusBadge } from "@/components/StatusBadge";
import type { BotJourney, Execution, JourneyEdge, JourneyNode, ProcessAgentDetail } from "@/lib/types";
import { formatDate, formatDuration, getConfigStr } from "./shared";

// Lead source types the wizard offers (dashboard/app/process-agents/new/page.tsx's
// LEAD_SOURCE_TYPES) that this POC does NOT yet dispatch calls for — shown as
// disabled options in the "coming soon" multi-source campaign mockup below.
const COMING_SOON_LEAD_SOURCE_TYPES: { value: string; label: string }[] = [
  { value: "webhook", label: "Webhook" },
  { value: "crm", label: "CRM" },
  { value: "google_sheet", label: "Google Sheet" },
  { value: "rest_api", label: "REST API" },
  { value: "csv", label: "CSV" },
];

function DispatchSection({
  agent,
  communicationConfig,
  journeyLoading,
  onDispatchSingleSource,
  dispatching,
  dispatchError,
  dispatchResult,
  botJourneys,
}: {
  agent: ProcessAgentDetail;
  communicationConfig: Record<string, unknown> | undefined;
  journeyLoading: boolean;
  onDispatchSingleSource: (params: Record<string, string>, botJourneyId?: number) => void;
  dispatching: boolean;
  dispatchError: string | null;
  dispatchResult: string | null;
  botJourneys: BotJourney[] | null;
}) {
  // Outbound params Chat360 expects in the call body (e.g. "@name", "@model_name") —
  // vary per process, so the user fills them in here rather than them being hardcoded.
  const [paramRows, setParamRows] = useState<{ key: string; value: string }[]>([
    { key: "", value: "" },
  ]);
  const orderedJourneys = (botJourneys ?? []).slice().sort((a, b) => a.order - b.order);
  const [selectedBotJourneyId, setSelectedBotJourneyId] = useState<number | "">("");

  if (journeyLoading) {
    return <div className="h-24 bg-surface-container rounded-xl animate-pulse" />;
  }

  const communicationType = getConfigStr(communicationConfig, "communication_type");
  const isOutbound = communicationType === "voice_outbound";
  // Manager order (no explicit ordering) is PK-ascending == creation order, so
  // the last element is the most-recently-created LeadSource — same row the
  // backend's launch_campaign() no-payload fallback reads from.
  const leadSource = agent.lead_sources[agent.lead_sources.length - 1];
  const isSingleSource = leadSource?.type === "single_source";
  const canDispatch = isOutbound && isSingleSource;
  const number = getConfigStr(leadSource?.configuration, "number");

  function updateRow(index: number, field: "key" | "value", value: string) {
    setParamRows((rows) => rows.map((row, i) => (i === index ? { ...row, [field]: value } : row)));
  }

  function addRow() {
    setParamRows((rows) => [...rows, { key: "", value: "" }]);
  }

  function removeRow(index: number) {
    setParamRows((rows) => (rows.length === 1 ? rows : rows.filter((_, i) => i !== index)));
  }

  function handleDispatch() {
    const params: Record<string, string> = {};
    for (const row of paramRows) {
      const key = row.key.trim();
      if (key) params[key] = row.value;
    }
    onDispatchSingleSource(params, selectedBotJourneyId === "" ? undefined : selectedBotJourneyId);
  }

  return (
    <Card className="p-5 space-y-4">
      <CardHeader
        title="Run this process"
        hint="Dispatch calls to this process agent's configured lead source."
      />

      {canDispatch ? (
        <div className="rounded-lg border border-border p-4 space-y-3">
          <div className="flex items-center justify-between gap-4 flex-wrap">
            <div>
              <p className="text-sm font-medium text-on-surface">Single Source</p>
              <p className="text-xs text-text-muted mt-0.5">{number || "No number configured"}</p>
            </div>
          </div>

          {orderedJourneys.length > 1 && (
            <div>
              <label className="block text-xs font-medium text-text-muted mb-1">Dispatch via</label>
              <select
                value={selectedBotJourneyId}
                onChange={(e) => setSelectedBotJourneyId(e.target.value ? Number(e.target.value) : "")}
                className="w-full max-w-xs px-2.5 py-1.5 rounded-lg border border-border bg-surface text-sm"
              >
                <option value="">Default ({orderedJourneys[0].name})</option>
                {orderedJourneys.map((j) => (
                  <option key={j.id} value={j.id}>
                    {j.name}
                    {j.voice_bot?.bot_name ? ` — ${j.voice_bot.bot_name}` : ""}
                  </option>
                ))}
              </select>
            </div>
          )}

          <div className="space-y-1.5">
            <p className="text-xs font-medium text-text-muted">Outbound params (e.g. @name, @model_name)</p>
            {paramRows.map((row, i) => (
              <div key={i} className="flex items-center gap-2">
                <input
                  value={row.key}
                  onChange={(e) => updateRow(i, "key", e.target.value)}
                  placeholder="@name"
                  className="flex-1 min-w-0 px-2.5 py-1.5 rounded-lg border border-border bg-surface text-sm font-mono"
                />
                <input
                  value={row.value}
                  onChange={(e) => updateRow(i, "value", e.target.value)}
                  placeholder="value"
                  className="flex-1 min-w-0 px-2.5 py-1.5 rounded-lg border border-border bg-surface text-sm"
                />
                <button
                  onClick={() => removeRow(i)}
                  disabled={paramRows.length === 1}
                  className="shrink-0 px-2 py-1.5 text-xs text-text-muted hover:text-bad disabled:opacity-40"
                  aria-label="Remove param"
                >
                  ✕
                </button>
              </div>
            ))}
            <button onClick={addRow} className="text-xs text-primary hover:underline">
              + Add param
            </button>
          </div>

          <div>
            <button
              onClick={handleDispatch}
              disabled={dispatching || !number}
              className="px-4 py-2 rounded-lg text-sm font-medium bg-primary text-on-primary hover:bg-primary-container disabled:opacity-60 transition-colors"
            >
              {dispatching ? "Dispatching…" : "Dispatch call"}
            </button>
            {dispatchResult && <p className="text-xs text-ok mt-1.5">{dispatchResult}</p>}
            {dispatchError && <p className="text-xs text-bad mt-1.5">{dispatchError}</p>}
          </div>
        </div>
      ) : (
        <div className="rounded-lg border border-dashed border-border p-4">
          <p className="text-sm text-text-muted">
            Dispatch is only available for a <span className="font-medium">Single Source</span> lead
            source on a <span className="font-medium">Voice Outbound</span> process — configure both
            in the wizard (Voice and Lead Source steps) to enable it here.
          </p>
        </div>
      )}

      <div>
        <div className="flex items-center gap-2 mb-2">
          <p className="text-sm font-medium text-on-surface">Multi-source campaigns</p>
          <span className="text-[10px] font-medium px-2 py-0.5 rounded-full bg-text-muted/15 text-text-muted uppercase tracking-wide">
            Coming soon
          </span>
        </div>
        <p className="text-xs text-text-muted mb-3">
          Running a campaign against a CRM, sheet, API, or CSV lead source from here is out of scope
          for this POC — this is a preview of the interface.
        </p>
        <div className="rounded-lg border border-dashed border-border p-4 space-y-3 opacity-60 pointer-events-none select-none">
          <div className="flex flex-wrap gap-3 items-end">
            <div className="flex-1 min-w-[180px]">
              <label className="block text-xs text-text-muted mb-1">Lead source</label>
              <select disabled className="w-full px-3 py-2 rounded-lg border border-border bg-surface text-sm">
                {COMING_SOON_LEAD_SOURCE_TYPES.map((t) => (
                  <option key={t.value}>{t.label}</option>
                ))}
              </select>
            </div>
            <div className="flex-1 min-w-[180px]">
              <label className="block text-xs text-text-muted mb-1">Campaign name</label>
              <input disabled placeholder="e.g. Free Service Reminder — Sept" className="w-full px-3 py-2 rounded-lg border border-border bg-surface text-sm" />
            </div>
            <button disabled className="px-4 py-2 rounded-lg text-sm font-medium bg-primary text-on-primary">
              Launch Campaign
            </button>
          </div>
        </div>
      </div>
    </Card>
  );
}

export function RunsTab({
  executions,
  loading,
  error,
  agent,
  journeyData,
  journeyLoading,
  onDispatchSingleSource,
  dispatching,
  dispatchError,
  dispatchResult,
  botJourneys,
}: {
  executions: Execution[] | null;
  loading: boolean;
  error: string | null;
  agent: ProcessAgentDetail;
  journeyData: { nodes: JourneyNode[]; edges: JourneyEdge[] } | null;
  journeyLoading: boolean;
  onDispatchSingleSource: (params: Record<string, string>, botJourneyId?: number) => void;
  dispatching: boolean;
  dispatchError: string | null;
  dispatchResult: string | null;
  botJourneys: BotJourney[] | null;
}) {
  const communicationConfig = journeyData?.nodes.find((n) => n.name === "Communication")?.config;

  return (
    <div className="space-y-6">
      <DispatchSection
        agent={agent}
        communicationConfig={communicationConfig}
        journeyLoading={journeyLoading && !journeyData}
        onDispatchSingleSource={onDispatchSingleSource}
        dispatching={dispatching}
        dispatchError={dispatchError}
        dispatchResult={dispatchResult}
        botJourneys={botJourneys}
      />

      {loading ? (
        <div className="h-32 bg-surface-container rounded-xl animate-pulse" />
      ) : error ? (
        <div className="text-sm text-bad bg-bad/10 border border-bad/30 rounded-lg px-4 py-3">{error}</div>
      ) : !executions || executions.length === 0 ? (
        <Card className="p-8 text-center">
          <p className="text-sm text-text-muted">
            No executions yet — this process hasn&apos;t run any calls.
          </p>
        </Card>
      ) : (
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
                    <td className="px-5 py-2.5 text-on-surface">
                      {ex.lead_id}
                    </td>
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
      )}
    </div>
  );
}
