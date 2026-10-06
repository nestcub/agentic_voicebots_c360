"use client";

import { useEffect, useState } from "react";
import { parseCampaignFile } from "@/lib/parseCampaignFile";
import { listChannels, listProcessAgents, getProcessAgent, launchCampaign } from "@/lib/telehubApi";
import type { Channel, ProcessAgentSummary, ProcessAgentDetail, ProcessAgentVariable } from "@/lib/types";

export interface UploadCampaignModalProps {
  open: boolean;
  onClose: () => void;
  onLaunched: (result: { campaignId: string; processAgentId: number }) => void; // parent handles what happens next
  // Allows pre-selecting the process (e.g. a future "Upload Campaign" button on a
  // specific Process Agent's page). Not used by the leads page today — it always
  // opens the modal without this, letting the user pick fresh each time.
  initialProcessAgentId?: number;
}

type ColumnMapping =
  | { type: "to" }
  | { type: "dnd" }
  | { type: "variable"; variableName: string }
  | { type: "ignore" };

type Step = "process" | "upload" | "mapping";

// ── Helpers ──────────────────────────────────────────────────────────────────

function slugify(header: string): string {
  const slug = header
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
  return `@${slug}`;
}

function looksLikePhoneColumn(header: string): boolean {
  const lower = header.toLowerCase().trim();
  return lower.includes("phone") || lower === "to" || lower === "mobile" || lower === "number";
}

function looksLikeDndColumn(header: string): boolean {
  const lower = header.toLowerCase().trim();
  return lower === "dnd" || lower === "do_not_disturb" || lower === "do not disturb";
}

function normalizeVariableName(raw: string): string {
  const trimmed = raw.trim();
  if (!trimmed) return "@";
  return trimmed.startsWith("@") ? trimmed : `@${trimmed}`;
}

// Finds a declared Process Agent variable whose key matches a column header,
// so the default mapping visibly targets a variable the process already expects.
function findMatchingVariable(
  header: string,
  variables: ProcessAgentVariable[],
): ProcessAgentVariable | undefined {
  const headerSlug = slugify(header).toLowerCase();
  return variables.find((v) => `@${v.key}`.trim().toLowerCase() === headerSlug);
}

function buildDefaultMapping(
  headers: string[],
  variables: ProcessAgentVariable[],
): Record<string, ColumnMapping> {
  const mapping: Record<string, ColumnMapping> = {};
  for (const header of headers) {
    if (looksLikePhoneColumn(header)) {
      mapping[header] = { type: "to" };
    } else if (looksLikeDndColumn(header)) {
      mapping[header] = { type: "dnd" };
    } else {
      const matched = findMatchingVariable(header, variables);
      const variableName = matched ? normalizeVariableName(matched.key) : slugify(header);
      mapping[header] = { type: "variable", variableName };
    }
  }
  return mapping;
}

// ── Small shared bits (mirrors app/process-agents/new/page.tsx conventions) ──

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-xs font-medium text-text-muted">{label}</span>
      {children}
    </label>
  );
}

const inputCls =
  "px-3 py-2 rounded-lg border border-border bg-surface text-sm text-on-surface focus:outline-none focus:ring-2 focus:ring-primary";

// ── Main component ───────────────────────────────────────────────────────────

export function UploadCampaignModal({ open, onClose, onLaunched, initialProcessAgentId }: UploadCampaignModalProps) {
  const [step, setStep] = useState<Step>("process");

  // Step 1: Process
  const [channels, setChannels] = useState<Channel[]>([]);
  const [channelsLoading, setChannelsLoading] = useState(false);
  const [channelsError, setChannelsError] = useState<string | null>(null);
  const [selectedChannelId, setSelectedChannelId] = useState<number | undefined>(undefined);

  const [processAgents, setProcessAgents] = useState<ProcessAgentSummary[]>([]);
  const [processAgentsLoading, setProcessAgentsLoading] = useState(false);
  const [processAgentsError, setProcessAgentsError] = useState<string | null>(null);
  const [selectedProcessAgentId, setSelectedProcessAgentId] = useState<number | undefined>(undefined);

  const [processAgentDetail, setProcessAgentDetail] = useState<ProcessAgentDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);

  // Step 2: Upload
  const [campaignName, setCampaignName] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [parseErrors, setParseErrors] = useState<string[]>([]);
  const [parsing, setParsing] = useState(false);

  // Step 3: Mapping
  const [headers, setHeaders] = useState<string[]>([]);
  const [rows, setRows] = useState<Record<string, string>[]>([]);
  const [mapping, setMapping] = useState<Record<string, ColumnMapping>>({});

  const [launching, setLaunching] = useState(false);
  const [launchError, setLaunchError] = useState<string | null>(null);

  // Load channels when the modal opens.
  useEffect(() => {
    if (!open) return;
    setChannelsLoading(true);
    setChannelsError(null);
    listChannels()
      .then((data) => setChannels(data))
      .catch((e) => setChannelsError(e instanceof Error ? e.message : "Failed to load channels"))
      .finally(() => setChannelsLoading(false));
  }, [open]);

  // Pre-select a process agent when opened with initialProcessAgentId — resolve its
  // channel first so the channel/process selects both land on the right value.
  useEffect(() => {
    if (!open || !initialProcessAgentId) return;
    setDetailLoading(true);
    setDetailError(null);
    getProcessAgent(initialProcessAgentId)
      .then((detail) => {
        setSelectedChannelId(detail.channel);
        setSelectedProcessAgentId(detail.id);
        setProcessAgentDetail(detail);
      })
      .catch((e) => setDetailError(e instanceof Error ? e.message : "Failed to load process agent"))
      .finally(() => setDetailLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, initialProcessAgentId]);

  // Load process agents whenever the selected channel changes.
  useEffect(() => {
    if (!open || selectedChannelId === undefined) {
      setProcessAgents([]);
      return;
    }
    setProcessAgentsLoading(true);
    setProcessAgentsError(null);
    listProcessAgents(selectedChannelId)
      .then((data) => setProcessAgents(data))
      .catch((e) => setProcessAgentsError(e instanceof Error ? e.message : "Failed to load process agents"))
      .finally(() => setProcessAgentsLoading(false));
  }, [open, selectedChannelId]);

  if (!open) return null;

  function resetAll() {
    setStep("process");
    setChannels([]);
    setChannelsLoading(false);
    setChannelsError(null);
    setSelectedChannelId(undefined);
    setProcessAgents([]);
    setProcessAgentsLoading(false);
    setProcessAgentsError(null);
    setSelectedProcessAgentId(undefined);
    setProcessAgentDetail(null);
    setDetailLoading(false);
    setDetailError(null);
    setCampaignName("");
    setFile(null);
    setParseErrors([]);
    setParsing(false);
    setHeaders([]);
    setRows([]);
    setMapping({});
    setLaunching(false);
    setLaunchError(null);
  }

  function handleClose() {
    resetAll();
    onClose();
  }

  function handleChannelChange(value: string) {
    const id = value ? Number(value) : undefined;
    setSelectedChannelId(id);
    setSelectedProcessAgentId(undefined);
    setProcessAgentDetail(null);
  }

  async function handleProcessNext() {
    if (selectedChannelId === undefined || selectedProcessAgentId === undefined || detailLoading) return;
    setDetailLoading(true);
    setDetailError(null);
    try {
      const detail = await getProcessAgent(selectedProcessAgentId);
      setProcessAgentDetail(detail);
      setStep("upload");
    } catch (e) {
      setDetailError(e instanceof Error ? e.message : "Failed to load process agent");
    } finally {
      setDetailLoading(false);
    }
  }

  async function handleUploadNext() {
    if (!file || !campaignName.trim() || parsing) return;
    setParsing(true);
    setParseErrors([]);
    try {
      const buffer = await file.arrayBuffer();
      const result = parseCampaignFile(buffer, file.name);
      if (result.errors.length > 0) {
        setParseErrors(result.errors);
        return;
      }
      setHeaders(result.headers);
      setRows(result.rows);
      setMapping(buildDefaultMapping(result.headers, processAgentDetail?.variables ?? []));
      setStep("mapping");
    } finally {
      setParsing(false);
    }
  }

  function handleBackToProcess() {
    setStep("process");
    setDetailError(null);
  }

  function handleBackToUpload() {
    setStep("upload");
    setLaunchError(null);
  }

  function updateMappingType(header: string, type: ColumnMapping["type"]) {
    setMapping((prev) => {
      const next = { ...prev };
      if (type === "to") {
        next[header] = { type: "to" };
      } else if (type === "dnd") {
        next[header] = { type: "dnd" };
      } else if (type === "ignore") {
        next[header] = { type: "ignore" };
      } else {
        const existing = prev[header];
        const variableName = existing?.type === "variable" ? existing.variableName : slugify(header);
        next[header] = { type: "variable", variableName };
      }
      return next;
    });
  }

  function updateVariableName(header: string, variableName: string) {
    setMapping((prev) => ({
      ...prev,
      [header]: { type: "variable", variableName },
    }));
  }

  function blurVariableName(header: string) {
    setMapping((prev) => {
      const existing = prev[header];
      if (!existing || existing.type !== "variable") return prev;
      return {
        ...prev,
        [header]: { type: "variable", variableName: normalizeVariableName(existing.variableName) },
      };
    });
  }

  const toHeaders = headers.filter((h) => mapping[h]?.type === "to");
  const toHeader = toHeaders[0];
  const dndHeaders = headers.filter((h) => mapping[h]?.type === "dnd");
  const dndHeader = dndHeaders[0];
  const mappingValid = toHeaders.length === 1 && dndHeaders.length <= 1;
  const validationMessage =
    toHeaders.length === 0
      ? "Select exactly one column as the phone number"
      : toHeaders.length > 1
        ? "Only one column can be the phone number"
        : dndHeaders.length > 1
          ? "Only one column can be the DND flag"
          : null;

  const variableHeaders = headers.filter((h) => mapping[h]?.type === "variable");
  const previewRows = rows.slice(0, 3);

  async function handleLaunch() {
    if (!mappingValid || !toHeader || launching || selectedProcessAgentId === undefined) return;
    setLaunching(true);
    setLaunchError(null);
    try {
      const leads = rows.map((row) => {
        const params: Record<string, string> = {};
        for (const header of variableHeaders) {
          const colMapping = mapping[header];
          if (colMapping?.type === "variable") {
            params[colMapping.variableName] = row[header];
          }
        }
        return {
          to_number: row[toHeader],
          params,
          ...(dndHeader ? { dnd: row[dndHeader] } : {}),
        };
      });
      const result = await launchCampaign(selectedProcessAgentId, {
        campaign_id: campaignName.trim(),
        leads,
      });
      onLaunched({ campaignId: result.campaign_id, processAgentId: selectedProcessAgentId });
    } catch (err) {
      setLaunchError(err instanceof Error ? err.message : String(err));
    } finally {
      setLaunching(false);
    }
  }

  const stepLabel =
    step === "process"
      ? "Step 1 of 3 — Select agent"
      : step === "upload"
        ? "Step 2 of 3 — Upload file"
        : "Step 3 of 3 — Map columns";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={handleClose}>
      <div
        className="bg-surface rounded-xl shadow-lg border border-border w-full max-w-2xl max-h-[90vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3 px-5 pt-4 pb-2">
          <div>
            <p className="text-base font-semibold text-on-surface">Upload Campaign</p>
            <p className="text-xs text-text-muted mt-0.5">{stepLabel}</p>
          </div>
          <button
            onClick={handleClose}
            aria-label="Close"
            className="text-text-muted hover:text-on-surface text-lg leading-none px-1"
          >
            ×
          </button>
        </div>

        <div className="px-5 pb-5">
          {step === "process" && (
            <div className="space-y-4">
              <Field label="Channel *">
                {channelsError ? (
                  <p className="text-sm text-bad">{channelsError}</p>
                ) : (
                  <select
                    value={selectedChannelId ?? ""}
                    onChange={(e) => handleChannelChange(e.target.value)}
                    disabled={channelsLoading}
                    className={inputCls}
                  >
                    <option value="">{channelsLoading ? "Loading…" : "— select a channel —"}</option>
                    {channels.map((d) => (
                      <option key={d.id} value={d.id}>
                        {d.name}
                      </option>
                    ))}
                  </select>
                )}
              </Field>

              <Field label="Agent *">
                {processAgentsError ? (
                  <p className="text-sm text-bad">{processAgentsError}</p>
                ) : (
                  <select
                    value={selectedProcessAgentId ?? ""}
                    onChange={(e) => setSelectedProcessAgentId(e.target.value ? Number(e.target.value) : undefined)}
                    disabled={selectedChannelId === undefined || processAgentsLoading}
                    className={inputCls}
                  >
                    <option value="">
                      {selectedChannelId === undefined
                        ? "Select a channel first"
                        : processAgentsLoading
                          ? "Loading…"
                          : "— select an agent —"}
                    </option>
                    {processAgents.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name}
                      </option>
                    ))}
                  </select>
                )}
              </Field>

              {detailError && (
                <div className="text-sm text-bad bg-bad/10 border border-bad/30 rounded-lg px-3 py-2">
                  {detailError}
                </div>
              )}

              <div className="flex justify-end items-center gap-3 pt-1">
                <button
                  onClick={handleProcessNext}
                  disabled={selectedChannelId === undefined || selectedProcessAgentId === undefined || detailLoading}
                  className="bg-primary hover:bg-primary-container disabled:opacity-50 disabled:cursor-not-allowed text-on-primary text-sm font-medium px-4 py-2 rounded-lg transition-colors"
                >
                  {detailLoading ? "Loading…" : "Next"}
                </button>
              </div>
            </div>
          )}

          {step === "upload" && (
            <div className="space-y-4">
              <Field label="Campaign name">
                <input
                  type="text"
                  value={campaignName}
                  onChange={(e) => setCampaignName(e.target.value)}
                  placeholder="e.g. diwali_offer_2026"
                  className={inputCls}
                />
              </Field>

              <Field label="Leads file (.xlsx or .csv)">
                <input
                  type="file"
                  accept=".xlsx,.csv"
                  onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                  className="text-sm text-on-surface file:mr-3 file:py-1.5 file:px-3 file:rounded-lg file:border-0 file:text-sm file:font-medium file:bg-primary/10 file:text-primary hover:file:bg-primary/20"
                />
              </Field>

              {parseErrors.length > 0 && (
                <ul className="text-sm text-bad list-disc list-inside space-y-0.5">
                  {parseErrors.map((err, i) => (
                    <li key={i}>{err}</li>
                  ))}
                </ul>
              )}

              <div className="flex justify-between items-center pt-1">
                <button onClick={handleBackToProcess} className="text-sm font-medium text-text-muted hover:text-on-surface">
                  ← Back
                </button>
                <div className="flex items-center gap-3">
                  {!parsing && (!campaignName.trim() || !file) && (
                    <p className="text-xs text-text-muted">
                      {!campaignName.trim() && !file
                        ? "Enter a campaign name and choose a file"
                        : !campaignName.trim()
                          ? "Enter a campaign name"
                          : "Choose a file"}
                    </p>
                  )}
                  <button
                    onClick={handleUploadNext}
                    disabled={!campaignName.trim() || !file || parsing}
                    title={!campaignName.trim() || !file ? "Enter a campaign name and choose a file first" : undefined}
                    className="bg-primary hover:bg-primary-container disabled:opacity-50 disabled:cursor-not-allowed text-on-primary text-sm font-medium px-4 py-2 rounded-lg transition-colors"
                  >
                    {parsing ? "Parsing…" : "Next"}
                  </button>
                </div>
              </div>
            </div>
          )}

          {step === "mapping" && (
            <div className="space-y-4">
              <div className="space-y-2">
                {headers.map((header) => {
                  const colMapping = mapping[header] ?? { type: "ignore" as const };
                  return (
                    <div
                      key={header}
                      className="flex items-center gap-3 flex-wrap p-2 rounded-lg bg-surface-container border border-border"
                    >
                      <span className="text-sm font-bold text-on-surface min-w-[120px]">{header}</span>
                      <select
                        value={colMapping.type}
                        onChange={(e) => updateMappingType(header, e.target.value as ColumnMapping["type"])}
                        className={inputCls}
                      >
                        <option value="to">Phone Number (to)</option>
                        <option value="dnd">DND Flag</option>
                        <option value="variable">Custom Variable</option>
                        <option value="ignore">Ignore this column</option>
                      </select>
                      {colMapping.type === "variable" && (
                        <input
                          type="text"
                          value={colMapping.variableName}
                          onChange={(e) => updateVariableName(header, e.target.value)}
                          onBlur={() => blurVariableName(header)}
                          className={`${inputCls} w-40`}
                        />
                      )}
                    </div>
                  );
                })}
              </div>

              {validationMessage && (
                <div className="text-sm text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
                  {validationMessage}
                </div>
              )}

              <div>
                <p className="text-xs font-medium text-text-muted uppercase tracking-wide mb-1.5">
                  Preview (first 3 rows)
                </p>
                <div className="overflow-x-auto border border-border rounded-lg">
                  <table className="min-w-full text-sm">
                    <thead className="bg-surface-container">
                      <tr>
                        <th className="text-left px-3 py-1.5 font-medium text-text-muted">To</th>
                        {variableHeaders.map((header) => {
                          const colMapping = mapping[header];
                          const name = colMapping?.type === "variable" ? colMapping.variableName : header;
                          return (
                            <th key={header} className="text-left px-3 py-1.5 font-medium text-text-muted">
                              {name}
                            </th>
                          );
                        })}
                      </tr>
                    </thead>
                    <tbody>
                      {previewRows.map((row, i) => (
                        <tr key={i} className="border-t border-border">
                          <td className="px-3 py-1.5 text-on-surface">{toHeader ? row[toHeader] : "—"}</td>
                          {variableHeaders.map((header) => (
                            <td key={header} className="px-3 py-1.5 text-on-surface">
                              {row[header]}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>

              {launchError && (
                <div className="text-sm text-bad bg-bad/10 border border-bad/30 rounded-lg px-3 py-2">
                  {launchError}
                </div>
              )}

              <div className="flex justify-between items-center pt-1">
                <button onClick={handleBackToUpload} className="text-sm font-medium text-text-muted hover:text-on-surface">
                  ← Back
                </button>
                <button
                  onClick={handleLaunch}
                  disabled={!mappingValid || launching}
                  className="bg-primary hover:bg-primary-container disabled:opacity-50 disabled:cursor-not-allowed text-on-primary text-sm font-medium px-4 py-2 rounded-lg transition-colors"
                >
                  {launching ? "Launching…" : "Launch Campaign"}
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
