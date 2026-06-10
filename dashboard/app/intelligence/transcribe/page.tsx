"use client";

import { useEffect, useRef, useState } from "react";
import { Card, CardHeader } from "@/components/Card";
import { RiUploadCloud2Line, RiCheckboxCircleLine, RiErrorWarningLine } from "react-icons/ri";

const INTEL_URL = process.env.NEXT_PUBLIC_INTEL_API_URL ?? "http://localhost:8001";
const INTEL_KEY = process.env.NEXT_PUBLIC_INTEL_API_KEY ?? "";

type Segment = { speaker: string; role: string; start: number; end: number; text: string };
type Insights = { agent_score: number | null; sentiment: string; summary: string; objection_patterns: string[]; qualification_signals: string[]; kb_gaps: string[] };
type TranscriptResult = { transcript_id: string; transcript: string; segments: Segment[]; duration: number; insights: Insights };
type StoredTranscript = { id: string; filename: string; duration: number; created_at: string };

const SENTIMENT_COLOR: Record<string, string> = { positive: "text-emerald-600", negative: "text-red-500", neutral: "text-gray-500" };

export default function TranscribePage() {
  const [clientId, setClientId] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [uploading, setUploading] = useState(false);
  const [results, setResults] = useState<TranscriptResult[]>([]);
  const [error, setError] = useState("");
  const [history, setHistory] = useState<StoredTranscript[]>([]);
  const [selected, setSelected] = useState<TranscriptResult | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const id = localStorage.getItem("intel_client_id") ?? "";
    setClientId(id);
    if (id) loadHistory(id);
  }, []);

  function loadHistory(id: string) {
    fetch(`/api/intelligence/transcripts?client_id=${encodeURIComponent(id)}`)
      .then((r) => r.json()).then((d) => setHistory(Array.isArray(d) ? d : [])).catch(() => {});
  }

  async function handleUpload() {
    if (!files.length || !clientId) { setError("Set a Client ID and select files first."); return; }
    setUploading(true); setError(""); setResults([]);
    const out: TranscriptResult[] = [];
    for (const file of files) {
      const form = new FormData();
      form.append("file", file);
      form.append("client_id", clientId);
      const res = await fetch(`${INTEL_URL}/transcribe`, { method: "POST", headers: { "x-api-key": INTEL_KEY }, body: form });
      if (!res.ok) { setError(`Failed: ${file.name}`); break; }
      out.push(await res.json());
    }
    setResults(out);
    setUploading(false);
    if (out.length) { setSelected(out[0]); loadHistory(clientId); }
  }

  const display = selected ?? results[0] ?? null;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-lg font-semibold text-gray-800">Transcribe</h1>
        <p className="text-xs text-gray-400 mt-0.5">Upload call recordings — Sarvam STT + LLM insight extraction</p>
      </div>

      {!clientId && (
        <div className="p-4 bg-amber-50 border border-amber-200 rounded-xl text-sm text-amber-700">
          No Client ID set. <a href="/intelligence" className="underline font-medium">Set one on the Intelligence hub.</a>
        </div>
      )}

      {/* Upload zone */}
      <Card className="p-5 space-y-4">
        <CardHeader title="Upload recordings" hint="WAV, MP3, M4A, AAC" />
        <div
          onClick={() => inputRef.current?.click()}
          onDrop={(e) => { e.preventDefault(); setFiles(Array.from(e.dataTransfer.files)); }}
          onDragOver={(e) => e.preventDefault()}
          className="border-2 border-dashed border-gray-200 rounded-xl p-8 text-center cursor-pointer hover:border-blue-400 transition-colors"
        >
          <RiUploadCloud2Line className="w-8 h-8 text-gray-300 mx-auto mb-2" />
          <p className="text-sm text-gray-500">{files.length ? `${files.length} file(s) selected` : "Drop files here or click to browse"}</p>
          <input ref={inputRef} type="file" multiple accept=".wav,.mp3,.m4a,.aac" className="hidden" onChange={(e) => setFiles(Array.from(e.target.files ?? []))} />
        </div>
        {error && <p className="text-sm text-red-500 flex items-center gap-1"><RiErrorWarningLine />{error}</p>}
        <button
          onClick={handleUpload}
          disabled={uploading || !files.length || !clientId}
          className="px-5 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-40 transition-colors"
        >
          {uploading ? "Transcribing…" : "Transcribe"}
        </button>
      </Card>

      {/* Results */}
      {display && (
        <div className="grid md:grid-cols-2 gap-6">
          <Card className="p-0 overflow-hidden">
            <CardHeader title="Transcript" hint={`${Math.round(display.duration)}s`} />
            <div className="divide-y divide-gray-100 max-h-[480px] overflow-y-auto">
              {display.segments.map((s, i) => (
                <div key={i} className="px-5 py-3">
                  <p className="text-xs font-semibold text-blue-600 mb-0.5">{s.role} <span className="text-gray-400 font-normal">{s.start.toFixed(1)}s</span></p>
                  <p className="text-sm text-gray-700">{s.text}</p>
                </div>
              ))}
            </div>
          </Card>

          <Card className="p-5 space-y-4">
            <CardHeader title="Insights" />
            <div className="flex items-center gap-4">
              <div className="text-center">
                <p className="text-3xl font-bold text-gray-800">{display.insights.agent_score ?? "—"}</p>
                <p className="text-xs text-gray-400">Agent Score</p>
              </div>
              <div>
                <p className={`text-sm font-medium capitalize ${SENTIMENT_COLOR[display.insights.sentiment] ?? ""}`}>{display.insights.sentiment}</p>
                <p className="text-xs text-gray-400">Sentiment</p>
              </div>
            </div>
            <p className="text-sm text-gray-600">{display.insights.summary}</p>
            {[
              { label: "Objection Patterns", items: display.insights.objection_patterns },
              { label: "Qualification Signals", items: display.insights.qualification_signals },
              { label: "KB Gaps", items: display.insights.kb_gaps },
            ].map(({ label, items }) => items.length > 0 && (
              <div key={label}>
                <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1">{label}</p>
                <ul className="space-y-0.5">
                  {items.map((item, i) => <li key={i} className="text-sm text-gray-700 flex items-start gap-1.5"><RiCheckboxCircleLine className="text-blue-400 mt-0.5 shrink-0" />{item}</li>)}
                </ul>
              </div>
            ))}
          </Card>
        </div>
      )}

      {/* History */}
      {history.length > 0 && (
        <Card className="p-0 overflow-hidden">
          <CardHeader title="Transcript history" hint={`${history.length} recordings`} />
          <div className="divide-y divide-gray-100">
            {history.map((t) => (
              <div key={t.id} className="flex items-center justify-between px-5 py-3">
                <div>
                  <p className="text-sm font-medium text-gray-800">{t.filename}</p>
                  <p className="text-xs text-gray-400">{Math.round(t.duration ?? 0)}s · {t.created_at?.slice(0, 10)}</p>
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}
