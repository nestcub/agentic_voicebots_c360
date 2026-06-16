"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Card, CardHeader } from "@/components/Card";
import { useTranscriptCache } from "@/context/IntelligenceContext";
import {
  RiUploadCloud2Line,
  RiCheckboxCircleLine,
  RiErrorWarningLine,
  RiRefreshLine,
  RiLoader4Line,
  RiCheckLine,
  RiCloseLine,
  RiEditLine,
  RiSaveLine,
} from "react-icons/ri";

const INTEL_URL = process.env.NEXT_PUBLIC_INTEL_API_URL ?? "http://localhost:8001";
const INTEL_KEY = process.env.NEXT_PUBLIC_INTEL_API_KEY ?? "";

// ── Types ──────────────────────────────────────────────────────────────────────

type FileItem = {
  file: File;
  status: "pending" | "processing" | "done" | "failed";
  transcriptId?: string;
  error?: string;
};

type BatchStatus = {
  batch_id: string;
  total: number;
  completed: number;
  failed: number;
  items: {
    filename: string;
    status: string;
    transcript_id?: string;
    error?: string;
  }[];
};

type Segment = { speaker: string; role: string; start: number; end: number; text: string };
type Insights = {
  agent_score: number | null;
  sentiment: string;
  summary: string;
  objection_patterns: string[];
  qualification_signals: string[];
  escalation_signals: string[];
  kb_gaps: string[];
  agent_failure_modes: string[];
  suggested_fixes: string[];
};
type TranscriptDetail = {
  id: string;
  filename: string;
  transcript_text: string;
  segments: Segment[];
  duration: number;
};
type InsightDetail = Insights & { insight_id: string; raw_insights_json?: Record<string, unknown> };

// ── Constants ──────────────────────────────────────────────────────────────────

const SENTIMENT_COLOR: Record<string, string> = {
  positive: "text-emerald-600",
  negative: "text-red-500",
  neutral: "text-gray-500",
};

const apiHeaders = () => ({ "x-api-key": INTEL_KEY });

// ── Helpers ────────────────────────────────────────────────────────────────────

function fmtSeconds(s: number) {
  return `${s}s`;
}

// ── Main page ──────────────────────────────────────────────────────────────────

export default function TranscribePage() {
  const [clientId, setClientId] = useState("");
  const { transcripts, refreshTranscripts } = useTranscriptCache();

  // provider & options
  const [provider, setProvider] = useState<"sarvam" | "deepgram">("sarvam");
  const [language, setLanguage] = useState<"hi-IN" | "mr-IN">("hi-IN");
  const [insightModel, setInsightModel] = useState<"sonnet" | "gpt-4.1">("sonnet");
  const [swapRoles, setSwapRoles] = useState(false);

  // file queue
  const [fileItems, setFileItems] = useState<FileItem[]>([]);
  const [batchId, setBatchId] = useState<string | null>(null);
  const [batchDone, setBatchDone] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState("");

  // transcript viewer
  const [viewingTranscript, setViewingTranscript] = useState<TranscriptDetail | null>(null);
  const [viewingInsights, setViewingInsights] = useState<InsightDetail | null>(null);
  const [loadingViewer, setLoadingViewer] = useState(false);
  const [editedText, setEditedText] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState("");
  const [viewerError, setViewerError] = useState<string | null>(null);

  const inputRef = useRef<HTMLInputElement>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const startTimeRef = useRef<number>(0);
  const transcribeAbortRef = useRef<AbortController | null>(null);
  const saveAbortRef = useRef<AbortController | null>(null);

  // ── Init ──

  useEffect(() => {
    setClientId(localStorage.getItem("intel_client_id") ?? "");
  }, []);

  // ── Drop zone ──

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    const dropped = Array.from(e.dataTransfer.files);
    setFileItems(dropped.map((f) => ({ file: f, status: "pending" })));
    setBatchId(null);
    setBatchDone(false);
    setSubmitError("");
  }, []);

  const onFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const picked = Array.from(e.target.files ?? []);
    setFileItems(picked.map((f) => ({ file: f, status: "pending" })));
    setBatchId(null);
    setBatchDone(false);
    setSubmitError("");
  };

  // ── Submit ──

  async function handleTranscribe() {
    if (!fileItems.length || !clientId) {
      setSubmitError("Set a Client ID and select at least one file.");
      return;
    }
    setSubmitting(true);
    setSubmitError("");
    setBatchDone(false);
    setElapsed(0);

    if (fileItems.length === 1) {
      setFileItems((prev) => [{ ...prev[0], status: "processing" }]);
      const form = new FormData();
      form.append("file", fileItems[0].file);
      form.append("client_id", clientId);
      form.append("provider", provider);
      form.append("language_code", language);
      form.append("insight_model", insightModel);
      form.append("swap_roles", String(swapRoles));
      try {
        transcribeAbortRef.current = new AbortController();
        const res = await fetch(`${INTEL_URL}/transcribe`, {
          method: "POST",
          headers: apiHeaders(),
          body: form,
          signal: transcribeAbortRef.current.signal,
        });
        if (!res.ok) throw new Error(`Server error ${res.status}`);
        const data: { transcript_id: string; transcript: string; segments: Segment[]; duration: number; insight_id: string; insights: Insights } = await res.json();
        setFileItems([{ file: fileItems[0].file, status: "done", transcriptId: data.transcript_id }]);
        setBatchDone(true);
        refreshTranscripts();
      } catch (err: unknown) {
        if (err instanceof Error && err.name === "AbortError") return;
        setFileItems((prev) => [{ ...prev[0], status: "failed", error: err instanceof Error ? err.message : "Failed." }]);
        setSubmitError(err instanceof Error ? err.message : "Submission failed.");
      } finally {
        setSubmitting(false);
      }
      return;
    }

    const form = new FormData();
    fileItems.forEach((fi) => form.append("files", fi.file));
    form.append("client_id", clientId);
    form.append("provider", provider);
    form.append("language_code", language);
    form.append("insight_model", insightModel);
    form.append("swap_roles", String(swapRoles));

    try {
      transcribeAbortRef.current = new AbortController();
      const res = await fetch(`${INTEL_URL}/transcribe/batch`, {
        method: "POST",
        headers: apiHeaders(),
        body: form,
        signal: transcribeAbortRef.current.signal,
      });
      if (!res.ok) throw new Error(`Server error ${res.status}`);
      const data: { batch_id: string } = await res.json();
      setBatchId(data.batch_id);
      setFileItems((prev) => prev.map((fi) => ({ ...fi, status: "processing" })));
      startPolling(data.batch_id);
      startTimer();
    } catch (err: unknown) {
      if (err instanceof Error && err.name === "AbortError") return;
      setSubmitError(err instanceof Error ? err.message : "Submission failed.");
    } finally {
      setSubmitting(false);
    }
  }

  function cancelTranscribe() {
    transcribeAbortRef.current?.abort();
    stopPolling();
    stopTimer();
    setFileItems((prev) => prev.map((fi) => ({ ...fi, status: "pending" })));
    setBatchId(null);
    setSubmitting(false);
    setBatchDone(false);
    setElapsed(0);
  }

  // ── Polling ──

  function startPolling(bid: string) {
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = setInterval(() => pollBatch(bid), 3000);
  }

  async function pollBatch(bid: string) {
    try {
      const res = await fetch(`${INTEL_URL}/batches/${bid}/status`, { headers: apiHeaders() });
      if (!res.ok) return;
      const data: BatchStatus = await res.json();
      applyBatchStatus(data);
      if (data.completed + data.failed === data.total) {
        stopPolling();
        stopTimer();
        setBatchDone(true);
        refreshTranscripts();
      }
    } catch {
      // swallow network errors during polling
    }
  }

  function applyBatchStatus(data: BatchStatus) {
    setFileItems((prev) =>
      prev.map((fi) => {
        const match = data.items.find((it) => it.filename === fi.file.name);
        if (!match) return fi;
        const status: FileItem["status"] =
          match.status === "done"
            ? "done"
            : match.status === "failed"
            ? "failed"
            : "processing";
        return {
          ...fi,
          status,
          transcriptId: match.transcript_id,
          error: match.error,
        };
      })
    );
  }

  function stopPolling() {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }

  // ── Timer ──

  function startTimer() {
    startTimeRef.current = Date.now();
    if (timerRef.current) clearInterval(timerRef.current);
    timerRef.current = setInterval(() => {
      setElapsed(Math.round((Date.now() - startTimeRef.current) / 1000));
    }, 1000);
  }

  function stopTimer() {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }

  useEffect(() => () => {
    stopPolling();
    stopTimer();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── Viewer ──

  async function loadTranscript(transcriptId: string) {
    setLoadingViewer(true);
    setSaveError("");
    setViewerError(null);
    setViewingTranscript(null);
    setViewingInsights(null);
    try {
      const [tRes, iRes] = await Promise.all([
        fetch(`${INTEL_URL}/transcripts/${transcriptId}`, { headers: apiHeaders() }),
        fetch(`${INTEL_URL}/transcripts/${transcriptId}/insights`, { headers: apiHeaders() }),
      ]);
      if (!tRes.ok) {
        setViewerError(`Failed to load transcript (${tRes.status})`);
        return;
      }
      const t: TranscriptDetail = await tRes.json();
      setViewingTranscript(t);
      setEditedText(t.transcript_text ?? "");
      if (iRes.ok) {
        const ins: InsightDetail = await iRes.json();
        setViewingInsights(ins);
      }
    } catch (err: unknown) {
      setViewerError(err instanceof Error ? err.message : "Failed to load transcript.");
    } finally {
      setLoadingViewer(false);
    }
  }

  async function handleSave() {
    if (!viewingTranscript) return;
    setSaving(true);
    setSaveError("");
    try {
      saveAbortRef.current = new AbortController();
      const res = await fetch(`${INTEL_URL}/transcripts/${viewingTranscript.id}`, {
        method: "PATCH",
        headers: { ...apiHeaders(), "Content-Type": "application/json" },
        body: JSON.stringify({ text: editedText, insight_model: insightModel }),
        signal: saveAbortRef.current.signal,
      });
      if (!res.ok) throw new Error(`Save failed: ${res.status}`);
      // Refresh insights after save
      const iRes = await fetch(`${INTEL_URL}/transcripts/${viewingTranscript.id}/insights`, {
        headers: apiHeaders(),
        signal: saveAbortRef.current.signal,
      });
      if (iRes.ok) setViewingInsights(await iRes.json());
    } catch (err: unknown) {
      if (err instanceof Error && err.name === "AbortError") return;
      setSaveError(err instanceof Error ? err.message : "Save failed.");
    } finally {
      setSaving(false);
    }
  }

  function cancelSave() {
    saveAbortRef.current?.abort();
    setSaving(false);
  }

  // ── Computed ──

  const completedCount = fileItems.filter((fi) => fi.status === "done").length;
  const failedCount = fileItems.filter((fi) => fi.status === "failed").length;
  const totalCount = fileItems.length;
  const progressPct =
    totalCount > 0 ? Math.round(((completedCount + failedCount) / totalCount) * 100) : 0;
  const showQueue = fileItems.length > 0;

  // ── Render ──────────────────────────────────────────────────────────────────

  return (
    <div className="space-y-6">
      {/* Page header */}
      <div>
        <h1 className="text-lg font-semibold text-gray-800">Transcribe</h1>
        <p className="text-xs text-gray-400 mt-0.5">
          Upload call recordings — STT + LLM insight extraction
        </p>
      </div>

      {!clientId && (
        <div className="p-4 bg-amber-50 border border-amber-200 rounded-xl text-sm text-amber-700">
          No Client ID set.{" "}
          <a href="/intelligence" className="underline font-medium">
            Set one on the Intelligence hub.
          </a>
        </div>
      )}

      {/* Provider + options bar */}
      <div className="flex flex-wrap items-center gap-4">
        {/* Provider pill toggle */}
        <div className="flex items-center bg-gray-100 rounded-full p-0.5 text-sm font-medium">
          {(["sarvam", "deepgram"] as const).map((p) => (
            <button
              key={p}
              onClick={() => setProvider(p)}
              className={`px-4 py-1.5 rounded-full transition-colors capitalize ${
                provider === p
                  ? "bg-white shadow text-blue-600"
                  : "text-gray-500 hover:text-gray-700"
              }`}
            >
              {p === "sarvam" ? "Sarvam" : "Deepgram"}
            </button>
          ))}
        </div>

        {/* Language pill toggle */}
        <div className="flex items-center bg-gray-100 rounded-full p-0.5 text-sm font-medium">
          {([["hi-IN", "Hindi"], ["mr-IN", "Marathi"]] as const).map(([code, label]) => (
            <button
              key={code}
              onClick={() => setLanguage(code)}
              className={`px-4 py-1.5 rounded-full transition-colors ${
                language === code
                  ? "bg-white shadow text-blue-600"
                  : "text-gray-500 hover:text-gray-700"
              }`}
            >
              {label}
            </button>
          ))}
        </div>

        {/* Insight model pill toggle */}
        <div className="flex items-center bg-gray-100 rounded-full p-0.5 text-sm font-medium">
          {([["sonnet", "Sonnet"], ["gpt-4.1", "GPT-4.1"]] as const).map(([model, label]) => (
            <button
              key={model}
              onClick={() => setInsightModel(model)}
              className={`px-4 py-1.5 rounded-full transition-colors ${
                insightModel === model
                  ? "bg-white shadow text-blue-600"
                  : "text-gray-500 hover:text-gray-700"
              }`}
            >
              {label}
            </button>
          ))}
        </div>

        {/* Swap roles checkbox */}
        <label className="flex items-center gap-2 text-sm text-gray-600 cursor-pointer select-none">
          <input
            type="checkbox"
            checked={swapRoles}
            onChange={(e) => setSwapRoles(e.target.checked)}
            className="w-4 h-4 accent-blue-600"
          />
          Customer speaks first
        </label>
      </div>

      {/* Upload zone */}
      <Card className="p-5 space-y-4">
        <CardHeader title="Upload recordings" hint="WAV, MP3, M4A, AAC" />
        <div
          onClick={() => inputRef.current?.click()}
          onDrop={onDrop}
          onDragOver={(e) => e.preventDefault()}
          className="border-2 border-dashed border-gray-200 rounded-xl p-8 text-center cursor-pointer hover:border-blue-400 transition-colors"
        >
          <RiUploadCloud2Line className="w-8 h-8 text-gray-300 mx-auto mb-2" />
          <p className="text-sm text-gray-500">
            {fileItems.length
              ? `${fileItems.length} file(s) selected`
              : "Drop files here or click to browse"}
          </p>
          <input
            ref={inputRef}
            type="file"
            multiple
            accept=".wav,.mp3,.m4a,.aac,.mp4,.mpeg,.mpg"
            className="hidden"
            onChange={onFileChange}
          />
        </div>

        {submitError && (
          <p className="text-sm text-red-500 flex items-center gap-1">
            <RiErrorWarningLine />
            {submitError}
          </p>
        )}

        <div className="flex items-center gap-3">
          <button
            onClick={handleTranscribe}
            disabled={submitting || !fileItems.length || !clientId}
            className="px-5 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-40 transition-colors"
          >
            {submitting ? "Submitting…" : "Transcribe"}
          </button>
          {submitting && (
            <button onClick={cancelTranscribe} className="px-4 py-2 text-sm font-medium text-red-600 border border-red-300 rounded-lg hover:bg-red-50 transition-colors">
              Cancel
            </button>
          )}
        </div>
      </Card>

      {/* Queue / History (left) + Viewer (right) — always rendered once there's something to show */}
      {(showQueue || transcripts.length > 0 || viewingTranscript || loadingViewer || viewerError) && (
        <div className="grid md:grid-cols-2 gap-6">
          {/* Left column: Queue when active, History when idle */}
          {showQueue ? (
            <Card className="p-0 overflow-hidden">
              <CardHeader
                title="Queue"
                hint={
                  batchId
                    ? batchDone
                      ? `${completedCount}/${totalCount} done`
                      : `${completedCount}/${totalCount} complete · ${fmtSeconds(elapsed)} elapsed`
                    : `${totalCount} file(s) ready`
                }
              />

              {/* Progress bar */}
              {batchId && (
                <div className="px-5 pb-3">
                  <div className="h-1.5 bg-gray-100 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-blue-500 rounded-full transition-all duration-500"
                      style={{ width: `${progressPct}%` }}
                    />
                  </div>
                </div>
              )}

              {/* File list */}
              <div className="divide-y divide-gray-100 max-h-[360px] overflow-y-auto">
                {fileItems.map((fi, i) => (
                  <div
                    key={i}
                    onClick={() => fi.transcriptId && loadTranscript(fi.transcriptId)}
                    className={`flex items-start gap-3 px-5 py-3 ${
                      fi.transcriptId ? "cursor-pointer hover:bg-gray-50" : ""
                    }`}
                  >
                    <span className="mt-0.5 shrink-0">
                      {fi.status === "pending" && (
                        <RiLoader4Line className="w-4 h-4 text-gray-300" />
                      )}
                      {fi.status === "processing" && (
                        <RiLoader4Line className="w-4 h-4 text-blue-500 animate-spin" />
                      )}
                      {fi.status === "done" && (
                        <RiCheckLine className="w-4 h-4 text-emerald-500" />
                      )}
                      {fi.status === "failed" && (
                        <RiCloseLine className="w-4 h-4 text-red-500" />
                      )}
                    </span>
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-gray-800 truncate">{fi.file.name}</p>
                      {fi.error && (
                        <p className="text-xs text-red-500 mt-0.5">{fi.error}</p>
                      )}
                      {fi.status === "done" && fi.transcriptId && (
                        <p className="text-xs text-blue-500 mt-0.5">Click to view</p>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </Card>
          ) : (
            <Card className="p-0 overflow-hidden">
              <CardHeader title="Transcript history" hint={`${transcripts.length} recordings`} />
              <div className="divide-y divide-gray-100 max-h-[420px] overflow-y-auto">
                {transcripts.length === 0 && (
                  <p className="px-5 py-6 text-sm text-gray-400">No recordings yet.</p>
                )}
                {transcripts.map((t) => (
                  <div
                    key={t.id}
                    onClick={() => loadTranscript(t.id)}
                    className="flex items-center justify-between px-5 py-3 cursor-pointer hover:bg-gray-50"
                  >
                    <div>
                      <p className="text-sm font-medium text-gray-800">{t.filename}</p>
                      <p className="text-xs text-gray-400">
                        {Math.round(t.duration ?? 0)}s · {t.created_at?.slice(0, 10)}
                      </p>
                    </div>
                    <RiRefreshLine className="w-4 h-4 text-gray-300" />
                  </div>
                ))}
              </div>
            </Card>
          )}

          {/* Right column: Transcript viewer — independent of queue state */}
          <Card className="p-0 overflow-hidden">
            <CardHeader
              title="Transcript viewer"
              hint={viewingTranscript ? viewingTranscript.filename : "Select a recording"}
            />

            {loadingViewer && (
              <div className="flex items-center justify-center py-16 text-gray-400 gap-2">
                <RiLoader4Line className="w-5 h-5 animate-spin" />
                <span className="text-sm">Loading…</span>
              </div>
            )}

            {!loadingViewer && viewerError && (
              <div className="flex flex-col items-center justify-center py-16 text-red-400 gap-2">
                <RiErrorWarningLine className="w-8 h-8" />
                <p className="text-sm">{viewerError}</p>
              </div>
            )}

            {!loadingViewer && !viewingTranscript && !viewerError && (
              <div className="flex flex-col items-center justify-center py-16 text-gray-300 gap-2">
                <RiEditLine className="w-8 h-8" />
                <p className="text-sm">Select a recording to view</p>
              </div>
            )}

            {!loadingViewer && viewingTranscript && (
              <div className="p-5 space-y-4 overflow-y-auto max-h-[600px]">
                {/* Editable textarea */}
                <div className="space-y-2">
                  <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
                    Transcript text
                  </p>
                  <textarea
                    value={editedText}
                    onChange={(e) => setEditedText(e.target.value)}
                    rows={8}
                    className="w-full text-sm text-gray-700 border border-gray-200 rounded-lg p-3 resize-y focus:outline-none focus:ring-2 focus:ring-blue-400"
                  />
                  {saveError && (
                    <p className="text-xs text-red-500 flex items-center gap-1">
                      <RiErrorWarningLine className="shrink-0" />
                      {saveError}
                    </p>
                  )}
                  <div className="flex items-center gap-3">
                    <button
                      onClick={handleSave}
                      disabled={saving}
                      className="flex items-center gap-1.5 px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-40 transition-colors"
                    >
                      {saving ? (
                        <RiLoader4Line className="w-4 h-4 animate-spin" />
                      ) : (
                        <RiSaveLine className="w-4 h-4" />
                      )}
                      {saving ? "Saving…" : "Save & Re-analyse"}
                    </button>
                    {saving && (
                      <button onClick={cancelSave} className="px-4 py-2 text-sm font-medium text-red-600 border border-red-300 rounded-lg hover:bg-red-50 transition-colors">
                        Cancel
                      </button>
                    )}
                  </div>
                </div>

                {/* Insights */}
                {viewingInsights && (
                  <div className="space-y-3 border-t border-gray-100 pt-4">
                    <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
                      Insights
                    </p>

                    {/* Score + sentiment */}
                    <div className="flex items-center gap-5">
                      <div className="text-center">
                        <p className="text-3xl font-bold text-gray-800">
                          {viewingInsights.agent_score ?? "—"}
                        </p>
                        <p className="text-xs text-gray-400">Agent Score</p>
                      </div>
                      <div>
                        <p
                          className={`text-sm font-medium capitalize ${
                            SENTIMENT_COLOR[viewingInsights.sentiment] ?? ""
                          }`}
                        >
                          {viewingInsights.sentiment}
                        </p>
                        <p className="text-xs text-gray-400">Sentiment</p>
                      </div>
                    </div>

                    {/* Summary */}
                    {viewingInsights.summary && (
                      <p className="text-sm text-gray-600">{viewingInsights.summary}</p>
                    )}

                    {/* Lists */}
                    {[
                      { label: "Objection Patterns",    items: viewingInsights.objection_patterns },
                      { label: "Qualification Signals", items: viewingInsights.qualification_signals },
                      { label: "Escalation Signals",    items: viewingInsights.escalation_signals },
                      { label: "KB Gaps",               items: viewingInsights.kb_gaps },
                      { label: "Agent Failure Modes",   items: viewingInsights.agent_failure_modes ?? (viewingInsights.raw_insights_json?.agent_failure_modes as string[]) ?? (viewingInsights.raw_insights_json?.bot_failure_modes as string[]) ?? [] },
                      { label: "Suggested Fixes",       items: viewingInsights.suggested_fixes  ?? (viewingInsights.raw_insights_json?.suggested_fixes  as string[]) ?? [] },
                    ].map(
                      ({ label, items }) =>
                        items?.length > 0 && (
                          <div key={label}>
                            <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1">
                              {label}
                            </p>
                            <ul className="space-y-0.5">
                              {items.map((item, idx) => (
                                <li
                                  key={idx}
                                  className="text-sm text-gray-700 flex items-start gap-1.5"
                                >
                                  <RiCheckboxCircleLine className="text-blue-400 mt-0.5 shrink-0" />
                                  {item}
                                </li>
                              ))}
                            </ul>
                          </div>
                        )
                    )}
                  </div>
                )}

                {/* Segments */}
                {viewingTranscript.segments?.length > 0 && (
                  <div className="border-t border-gray-100 pt-4 space-y-1">
                    <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
                      Segments
                    </p>
                    <div className="max-h-[240px] overflow-y-auto space-y-2">
                      {viewingTranscript.segments.map((s, i) => (
                        <div key={i}>
                          <p className="text-xs font-semibold text-blue-600">
                            {s.role}{" "}
                            <span className="text-gray-400 font-normal">
                              {s.start.toFixed(1)}s
                            </span>
                          </p>
                          <p className="text-sm text-gray-700">{s.text}</p>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </Card>
        </div>
      )}
    </div>
  );
}
