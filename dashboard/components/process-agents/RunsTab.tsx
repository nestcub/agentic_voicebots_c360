import { useState } from "react";
import { History, PhoneOutgoing, Plus, Rocket, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { EmptyState } from "@/components/common/EmptyState";
import { ErrorAlert } from "@/components/common/ErrorAlert";
import { ExecutionStatusBadge, ToneBadge } from "@/components/StatusBadge";
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
  const [paramRows, setParamRows] = useState<{ key: string; value: string }[]>([{ key: "", value: "" }]);
  const orderedJourneys = (botJourneys ?? []).slice().sort((a, b) => a.order - b.order);
  const [selectedBotJourneyId, setSelectedBotJourneyId] = useState<number | "">("");

  if (journeyLoading) {
    return <Skeleton className="h-32 rounded-xl" />;
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
    <Card>
      <CardHeader className="flex flex-row items-start gap-3">
        <div className="w-10 h-10 shrink-0 rounded-lg bg-accent text-primary flex items-center justify-center">
          <Rocket className="w-5 h-5" />
        </div>
        <div className="space-y-1">
          <CardTitle>Run this process</CardTitle>
          <CardDescription>Dispatch calls to this process agent&apos;s configured lead source.</CardDescription>
        </div>
      </CardHeader>
      <CardContent className="space-y-6">
        {canDispatch ? (
          <div className="rounded-lg border border-border p-4 space-y-4">
            <div className="flex items-center gap-3">
              <PhoneOutgoing className="w-4 h-4 text-muted-foreground" />
              <div>
                <p className="text-sm font-medium text-foreground">Single Source</p>
                <p className="text-xs text-muted-foreground font-mono mt-0.5">{number || "No number configured"}</p>
              </div>
            </div>

            {orderedJourneys.length > 1 && (
              <div className="space-y-1.5 max-w-xs">
                <Label htmlFor="runs-dispatch-via" className="text-xs text-muted-foreground">
                  Dispatch via
                </Label>
                <NativeSelect
                  id="runs-dispatch-via"
                  value={selectedBotJourneyId}
                  onChange={(e) => setSelectedBotJourneyId(e.target.value ? Number(e.target.value) : "")}
                >
                  <NativeSelectOption value="">Default ({orderedJourneys[0].name})</NativeSelectOption>
                  {orderedJourneys.map((j) => (
                    <NativeSelectOption key={j.id} value={j.id}>
                      {j.name}
                      {j.voice_bot?.bot_name ? ` — ${j.voice_bot.bot_name}` : ""}
                    </NativeSelectOption>
                  ))}
                </NativeSelect>
              </div>
            )}

            <div className="space-y-2">
              <p className="text-xs font-medium text-muted-foreground">Outbound params (e.g. @name, @model_name)</p>
              {paramRows.map((row, i) => (
                <div key={i} className="flex items-center gap-2">
                  <Input
                    value={row.key}
                    onChange={(e) => updateRow(i, "key", e.target.value)}
                    placeholder="@name"
                    className="flex-1 min-w-0 font-mono"
                    aria-label="Param key"
                  />
                  <Input
                    value={row.value}
                    onChange={(e) => updateRow(i, "value", e.target.value)}
                    placeholder="value"
                    className="flex-1 min-w-0"
                    aria-label="Param value"
                  />
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={() => removeRow(i)}
                    disabled={paramRows.length === 1}
                    aria-label="Remove param"
                    className="text-muted-foreground hover:text-bad"
                  >
                    <X />
                  </Button>
                </div>
              ))}
              <Button variant="link" size="sm" onClick={addRow} className="px-0">
                <Plus /> Add param
              </Button>
            </div>

            <div>
              <Button onClick={handleDispatch} disabled={dispatching || !number}>
                {dispatching ? <Spinner /> : <PhoneOutgoing />}
                Dispatch call
              </Button>
              {dispatchResult && <p className="text-xs text-ok mt-2">{dispatchResult}</p>}
              {dispatchError && <p className="text-xs text-bad mt-2">{dispatchError}</p>}
            </div>
          </div>
        ) : (
          <div className="rounded-lg border border-dashed border-border p-4">
            <p className="text-sm text-muted-foreground">
              Dispatch is only available for a <span className="font-medium">Single Source</span> lead source on a{" "}
              <span className="font-medium">Voice Outbound</span> process — configure both in the wizard (Voice and
              Lead Source steps) to enable it here.
            </p>
          </div>
        )}

        <div>
          <div className="flex items-center gap-2 mb-2">
            <p className="text-sm font-medium text-foreground">Multi-source campaigns</p>
            <ToneBadge tone="muted" className="uppercase tracking-wide text-[10px]">
              Coming soon
            </ToneBadge>
          </div>
          <p className="text-xs text-muted-foreground mb-3">
            Running a campaign against a CRM, sheet, API, or CSV lead source from here is out of scope for this POC
            — this is a preview of the interface.
          </p>
          <div className="rounded-lg border border-dashed border-border p-4 opacity-60 pointer-events-none select-none">
            <div className="flex flex-wrap gap-3 items-end">
              <div className="flex-1 min-w-44 space-y-1.5">
                <Label className="text-xs text-muted-foreground">Lead source</Label>
                <NativeSelect disabled>
                  {COMING_SOON_LEAD_SOURCE_TYPES.map((t) => (
                    <NativeSelectOption key={t.value}>{t.label}</NativeSelectOption>
                  ))}
                </NativeSelect>
              </div>
              <div className="flex-1 min-w-44 space-y-1.5">
                <Label className="text-xs text-muted-foreground">Campaign name</Label>
                <Input disabled placeholder="e.g. Free Service Reminder — Sept" />
              </div>
              <Button disabled>Launch Campaign</Button>
            </div>
          </div>
        </div>
      </CardContent>
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
        <Skeleton className="h-40 rounded-xl" />
      ) : error ? (
        <ErrorAlert message={error} />
      ) : !executions || executions.length === 0 ? (
        <EmptyState
          icon={History}
          title="No executions yet"
          description="This process hasn't run any calls."
        />
      ) : (
        <Card className="gap-0 py-0 overflow-hidden">
          <div className="px-5 py-4 border-b border-border">
            <p className="font-semibold text-foreground">Runs</p>
            <p className="text-xs text-muted-foreground mt-0.5">
              {executions.length} execution{executions.length === 1 ? "" : "s"}
            </p>
          </div>
          <Table>
            <TableHeader className="bg-muted">
              <TableRow>
                <TableHead className="px-5">Lead</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Started</TableHead>
                <TableHead>Duration</TableHead>
                <TableHead className="pr-5">Current Node</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {executions.map((ex) => (
                <TableRow key={ex.id}>
                  <TableCell className="px-5 font-medium">{ex.lead_id}</TableCell>
                  <TableCell>
                    <ExecutionStatusBadge status={ex.status} />
                  </TableCell>
                  <TableCell className="text-muted-foreground">{formatDate(ex.started_at)}</TableCell>
                  <TableCell className="text-muted-foreground tabular-nums">{formatDuration(ex.duration)}</TableCell>
                  <TableCell className="pr-5 text-muted-foreground">{ex.current_node || "—"}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Card>
      )}
    </div>
  );
}
