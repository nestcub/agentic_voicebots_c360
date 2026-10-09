"use client";

import { useEffect, useState } from "react";
import { ArrowLeft, ArrowRight, Check, FileSpreadsheet, Rocket, Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select";
import { Spinner } from "@/components/ui/spinner";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { ErrorAlert } from "@/components/common/ErrorAlert";
import { cn } from "@/lib/utils";
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

// ── Small shared bits ──────────────────────────────────────────────────────────

function Field({ label, htmlFor, children }: { label: string; htmlFor?: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={htmlFor} className="text-xs text-muted-foreground">
        {label}
      </Label>
      {children}
    </div>
  );
}

const STEPS: { key: Step; label: string }[] = [
  { key: "process", label: "Select agent" },
  { key: "upload", label: "Upload file" },
  { key: "mapping", label: "Map columns" },
];

function StepIndicator({ step }: { step: Step }) {
  const current = STEPS.findIndex((s) => s.key === step);
  return (
    <ol className="flex items-center gap-2">
      {STEPS.map((s, i) => (
        <li key={s.key} className="flex items-center gap-2 flex-1 last:flex-none">
          <span
            className={cn(
              "w-6 h-6 shrink-0 rounded-full flex items-center justify-center text-xs font-semibold",
              i < current && "bg-primary text-primary-foreground",
              i === current && "bg-primary text-primary-foreground ring-4 ring-primary/15",
              i > current && "bg-muted text-muted-foreground",
            )}
          >
            {i < current ? <Check className="w-3.5 h-3.5" /> : i + 1}
          </span>
          <span
            className={cn(
              "text-xs whitespace-nowrap",
              i === current ? "font-medium text-foreground" : "text-muted-foreground",
            )}
          >
            {s.label}
          </span>
          {i < STEPS.length - 1 && (
            <span className={cn("h-px flex-1 min-w-4", i < current ? "bg-primary" : "bg-border")} />
          )}
        </li>
      ))}
    </ol>
  );
}

function FileDropZone({ file, onFile }: { file: File | null; onFile: (file: File | null) => void }) {
  const [dragging, setDragging] = useState(false);
  return (
    <label
      htmlFor="campaign-file"
      onDragOver={(e) => {
        e.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDragging(false);
        onFile(e.dataTransfer.files?.[0] ?? null);
      }}
      className={cn(
        "flex flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed px-4 py-8 text-center cursor-pointer transition-colors",
        dragging ? "border-primary bg-accent" : "border-border hover:border-primary/50 hover:bg-muted/50",
      )}
    >
      <input
        id="campaign-file"
        type="file"
        accept=".xlsx,.csv"
        className="sr-only"
        onChange={(e) => onFile(e.target.files?.[0] ?? null)}
      />
      {file ? (
        <>
          <span className="w-10 h-10 rounded-lg bg-ok/10 text-ok flex items-center justify-center">
            <FileSpreadsheet className="w-5 h-5" />
          </span>
          <p className="text-sm font-medium text-foreground">{file.name}</p>
          <p className="text-xs text-muted-foreground">{(file.size / 1024).toFixed(1)} KB · click to choose another</p>
        </>
      ) : (
        <>
          <span className="w-10 h-10 rounded-lg bg-accent text-primary flex items-center justify-center">
            <Upload className="w-5 h-5" />
          </span>
          <p className="text-sm font-medium text-foreground">Drop your leads file here, or click to browse</p>
          <p className="text-xs text-muted-foreground">.xlsx or .csv</p>
        </>
      )}
    </label>
  );
}

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

  return (
    <Dialog open={open} onOpenChange={(o) => !o && !launching && handleClose()}>
      <DialogContent className="sm:max-w-2xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Upload Campaign</DialogTitle>
          <DialogDescription>Launch a list of leads against a process agent.</DialogDescription>
        </DialogHeader>

        <StepIndicator step={step} />

        {step === "process" && (
          <div className="space-y-4">
            <Field label="Channel *" htmlFor="upload-channel">
              {channelsError ? (
                <p className="text-sm text-bad">{channelsError}</p>
              ) : (
                <NativeSelect
                  id="upload-channel"
                  value={selectedChannelId ?? ""}
                  onChange={(e) => handleChannelChange(e.target.value)}
                  disabled={channelsLoading}
                >
                  <NativeSelectOption value="">
                    {channelsLoading ? "Loading…" : "— select a channel —"}
                  </NativeSelectOption>
                  {channels.map((d) => (
                    <NativeSelectOption key={d.id} value={d.id}>
                      {d.name}
                    </NativeSelectOption>
                  ))}
                </NativeSelect>
              )}
            </Field>

            <Field label="Agent *" htmlFor="upload-agent">
              {processAgentsError ? (
                <p className="text-sm text-bad">{processAgentsError}</p>
              ) : (
                <NativeSelect
                  id="upload-agent"
                  value={selectedProcessAgentId ?? ""}
                  onChange={(e) => setSelectedProcessAgentId(e.target.value ? Number(e.target.value) : undefined)}
                  disabled={selectedChannelId === undefined || processAgentsLoading}
                >
                  <NativeSelectOption value="">
                    {selectedChannelId === undefined
                      ? "Select a channel first"
                      : processAgentsLoading
                        ? "Loading…"
                        : "— select an agent —"}
                  </NativeSelectOption>
                  {processAgents.map((p) => (
                    <NativeSelectOption key={p.id} value={p.id}>
                      {p.name}
                    </NativeSelectOption>
                  ))}
                </NativeSelect>
              )}
            </Field>

            {detailError && <ErrorAlert message={detailError} />}

            <div className="flex justify-end pt-1">
              <Button
                onClick={handleProcessNext}
                disabled={selectedChannelId === undefined || selectedProcessAgentId === undefined || detailLoading}
              >
                {detailLoading && <Spinner />}
                Next <ArrowRight />
              </Button>
            </div>
          </div>
        )}

        {step === "upload" && (
          <div className="space-y-4">
            <Field label="Campaign name" htmlFor="upload-campaign-name">
              <Input
                id="upload-campaign-name"
                value={campaignName}
                onChange={(e) => setCampaignName(e.target.value)}
                placeholder="e.g. diwali_offer_2026"
              />
            </Field>

            <Field label="Leads file">
              <FileDropZone file={file} onFile={setFile} />
            </Field>

            {parseErrors.length > 0 && (
              <ul className="text-sm text-bad list-disc list-inside space-y-0.5">
                {parseErrors.map((err, i) => (
                  <li key={i}>{err}</li>
                ))}
              </ul>
            )}

            <div className="flex justify-between items-center pt-1">
              <Button variant="ghost" onClick={handleBackToProcess}>
                <ArrowLeft /> Back
              </Button>
              <div className="flex items-center gap-3">
                {!parsing && (!campaignName.trim() || !file) && (
                  <p className="text-xs text-muted-foreground hidden sm:block">
                    {!campaignName.trim() && !file
                      ? "Enter a campaign name and choose a file"
                      : !campaignName.trim()
                        ? "Enter a campaign name"
                        : "Choose a file"}
                  </p>
                )}
                <Button onClick={handleUploadNext} disabled={!campaignName.trim() || !file || parsing}>
                  {parsing && <Spinner />}
                  Next <ArrowRight />
                </Button>
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
                    className="flex items-center gap-3 flex-wrap p-2.5 rounded-lg bg-muted/60 border border-border"
                  >
                    <span className="text-sm font-semibold text-foreground min-w-30 truncate">{header}</span>
                    <div className="w-48">
                      <NativeSelect
                        size="sm"
                        value={colMapping.type}
                        onChange={(e) => updateMappingType(header, e.target.value as ColumnMapping["type"])}
                        aria-label={`Mapping for ${header}`}
                        className="bg-card"
                      >
                        <NativeSelectOption value="to">Phone Number (to)</NativeSelectOption>
                        <NativeSelectOption value="dnd">DND Flag</NativeSelectOption>
                        <NativeSelectOption value="variable">Custom Variable</NativeSelectOption>
                        <NativeSelectOption value="ignore">Ignore this column</NativeSelectOption>
                      </NativeSelect>
                    </div>
                    {colMapping.type === "variable" && (
                      <Input
                        value={colMapping.variableName}
                        onChange={(e) => updateVariableName(header, e.target.value)}
                        onBlur={() => blurVariableName(header)}
                        aria-label={`Variable name for ${header}`}
                        className="h-8 w-40 font-mono text-xs bg-card"
                      />
                    )}
                  </div>
                );
              })}
            </div>

            {validationMessage && (
              <div className="text-sm text-warn bg-warn/10 border border-warn/30 rounded-lg px-3 py-2">
                {validationMessage}
              </div>
            )}

            <div>
              <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-1.5">
                Preview (first 3 rows)
              </p>
              <div className="border border-border rounded-lg overflow-hidden">
                <Table>
                  <TableHeader className="bg-muted">
                    <TableRow>
                      <TableHead>To</TableHead>
                      {variableHeaders.map((header) => {
                        const colMapping = mapping[header];
                        const name = colMapping?.type === "variable" ? colMapping.variableName : header;
                        return (
                          <TableHead key={header} className="font-mono text-xs">
                            {name}
                          </TableHead>
                        );
                      })}
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {previewRows.map((row, i) => (
                      <TableRow key={i}>
                        <TableCell className="font-mono text-xs">{toHeader ? row[toHeader] : "—"}</TableCell>
                        {variableHeaders.map((header) => (
                          <TableCell key={header}>{row[header]}</TableCell>
                        ))}
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            </div>

            {launchError && <ErrorAlert message={launchError} />}

            <div className="flex justify-between items-center pt-1">
              <Button variant="ghost" onClick={handleBackToUpload}>
                <ArrowLeft /> Back
              </Button>
              <Button onClick={handleLaunch} disabled={!mappingValid || launching}>
                {launching ? <Spinner /> : <Rocket />}
                Launch Campaign
              </Button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
