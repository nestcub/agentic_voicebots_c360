"use client";

import { useRef, useState } from "react";
import { useRouter } from "next/navigation";

const INTEL_URL = process.env.NEXT_PUBLIC_INTEL_API_URL ?? "http://localhost:8001";
const INTEL_KEY = process.env.NEXT_PUBLIC_INTEL_API_KEY ?? "";

const apiHeaders = () => ({
  "x-api-key": INTEL_KEY,
  "Content-Type": "application/json",
});

type TranscriptRow = {
  id: number;
  filename: string;
  text: string;
  failures: string;
};

export default function ImportBotPage() {
  const router = useRouter();
  const [botName, setBotName] = useState("");
  const [systemPrompt, setSystemPrompt] = useState("");
  const [rows, setRows] = useState<TranscriptRow[]>([{ id: 1, filename: "", text: "", failures: "" }]);
  const [submitting, setSubmitting] = useState(false);
  const [pollStatus, setPollStatus] = useState<string | null>(null);
  const [pollDone, setPollDone] = useState(0);
  const [pollTotal, setPollTotal] = useState(0);
  const [error, setError] = useState("");
  const spFileRef = useRef<HTMLInputElement>(null);
  const nextId = useRef(2);

  function addRow() {
    setRows((prev) => [...prev, { id: nextId.current++, filename: "", text: "", failures: "" }]);
  }

  function removeRow(id: number) {
    setRows((prev) => prev.filter((r) => r.id !== id));
  }

  function updateRow(id: number, field: keyof TranscriptRow, value: string) {
    setRows((prev) => prev.map((r) => (r.id === id ? { ...r, [field]: value } : r)));
  }

  function readFileIntoState(file: File, setter: (text: string, filename: string) => void) {
    const reader = new FileReader();
    reader.onload = (e) => setter((e.target?.result as string) ?? "", file.name);
    reader.readAsText(file);
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!botName.trim()) { setError("Bot name is required."); return; }
    if (!systemPrompt.trim()) { setError("System prompt is required."); return; }
    setError("");
    setSubmitting(true);
    setPollStatus("submitting");

    const transcripts = rows
      .filter((r) => r.text.trim())
      .map((r) => ({
        filename: r.filename || "pasted.txt",
        text: r.text,
        reported_failures: r.failures,
      }));

    let clientId = "";
    try {
      const res = await fetch(`${INTEL_URL}/bots/import`, {
        method: "POST",
        headers: apiHeaders(),
        body: JSON.stringify({ bot_name: botName, system_prompt: systemPrompt, transcripts }),
      });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        throw new Error(d.detail || `Server error ${res.status}`);
      }
      const data = await res.json();
      clientId = data.client_id;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Submission failed.");
      setSubmitting(false);
      setPollStatus(null);
      return;
    }

    // Poll until ready or failed
    const poll = async () => {
      try {
        const res = await fetch(`${INTEL_URL}/bots/import/${clientId}/status`, { headers: { "x-api-key": INTEL_KEY } });
        if (!res.ok) { setError("Status check failed."); setSubmitting(false); return; }
        const data = await res.json();
        setPollStatus(data.status);
        setPollDone(data.done ?? 0);
        setPollTotal(data.total ?? 0);
        if (data.status === "ready") {
          router.push(`/intelligence/bot?client_id=${encodeURIComponent(clientId)}`);
        } else if (data.status === "failed") {
          setError("Ingestion failed. Check the server logs.");
          setSubmitting(false);
        } else {
          setTimeout(poll, 2000);
        }
      } catch {
        setError("Polling failed.");
        setSubmitting(false);
      }
    };
    setTimeout(poll, 1500);
  }

  const isProcessing = submitting && pollStatus !== null && pollStatus !== "ready" && pollStatus !== "failed";

  return (
    <div className="max-w-2xl mx-auto py-8 px-4 space-y-6">
      <div>
        <h1 className="text-lg font-semibold text-gray-800">Add existing bot</h1>
        <p className="text-sm text-gray-400 mt-0.5">
          Import a production bot&apos;s system prompt and call transcripts to test it with the LLM.
        </p>
      </div>

      {error && (
        <div className="p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-600">{error}</div>
      )}

      {isProcessing && (
        <div className="p-4 bg-blue-50 border border-blue-200 rounded-xl text-sm text-blue-700 flex items-center gap-3">
          <span className="w-4 h-4 border-2 border-blue-500 border-t-transparent rounded-full animate-spin shrink-0" />
          {pollTotal > 0
            ? `Processing transcripts… ${pollDone} / ${pollTotal} done`
            : "Submitting…"}
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-5">
        {/* Bot name */}
        <div className="bg-white border border-gray-200 rounded-xl p-6 space-y-4 shadow-sm">
          <h2 className="text-base font-semibold text-gray-800">Bot details</h2>
          <div className="space-y-1">
            <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Bot name</label>
            <input
              type="text"
              value={botName}
              onChange={(e) => setBotName(e.target.value)}
              placeholder="e.g. Adani service bot (prod)"
              className="w-full rounded-lg border border-gray-200 text-sm text-gray-800 placeholder-gray-400 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-400"
            />
          </div>

          {/* System prompt */}
          <div className="space-y-1">
            <div className="flex items-center justify-between">
              <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide">System prompt</label>
              <button
                type="button"
                onClick={() => spFileRef.current?.click()}
                className="text-xs text-blue-600 hover:underline"
              >
                Load from file
              </button>
              <input
                ref={spFileRef}
                type="file"
                accept=".txt,.md"
                className="hidden"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) readFileIntoState(f, (text) => setSystemPrompt(text));
                }}
              />
            </div>
            <textarea
              value={systemPrompt}
              onChange={(e) => setSystemPrompt(e.target.value)}
              placeholder="Paste the full system prompt here…"
              className="w-full rounded-lg border border-gray-200 text-sm text-gray-800 placeholder-gray-400 p-3 resize-none focus:outline-none focus:ring-2 focus:ring-blue-400 min-h-[160px] font-mono text-xs"
            />
            {systemPrompt && (
              <p className="text-xs text-gray-400">{systemPrompt.length.toLocaleString()} chars</p>
            )}
          </div>
        </div>

        {/* Transcript rows */}
        <div className="bg-white border border-gray-200 rounded-xl p-6 space-y-4 shadow-sm">
          <div className="flex items-center justify-between">
            <h2 className="text-base font-semibold text-gray-800">
              Call transcripts{" "}
              <span className="text-gray-400 font-normal text-sm">(optional)</span>
            </h2>
            <button
              type="button"
              onClick={addRow}
              className="text-sm text-blue-600 hover:underline"
            >
              + Add transcript
            </button>
          </div>

          {rows.map((row, idx) => (
            <div key={row.id} className="border border-gray-200 rounded-lg p-4 space-y-3 bg-gray-50">
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium text-gray-500">Transcript {idx + 1}</span>
                {rows.length > 1 && (
                  <button
                    type="button"
                    onClick={() => removeRow(row.id)}
                    className="text-xs text-red-400 hover:text-red-600"
                  >
                    Remove
                  </button>
                )}
              </div>

              {/* Transcript text */}
              <div className="space-y-1">
                <div className="flex items-center justify-between">
                  <label className="text-xs text-gray-500">Transcript text</label>
                  <label className="text-xs text-blue-600 hover:underline cursor-pointer">
                    Load file
                    <input
                      type="file"
                      accept=".txt,.md"
                      className="hidden"
                      onChange={(e) => {
                        const f = e.target.files?.[0];
                        if (f) readFileIntoState(f, (text, name) => {
                          updateRow(row.id, "text", text);
                          updateRow(row.id, "filename", name);
                        });
                      }}
                    />
                  </label>
                </div>
                <textarea
                  value={row.text}
                  onChange={(e) => updateRow(row.id, "text", e.target.value)}
                  placeholder="Paste transcript text here…"
                  className="w-full rounded-lg border border-gray-200 text-sm text-gray-800 placeholder-gray-400 p-3 resize-none focus:outline-none focus:ring-2 focus:ring-blue-400 min-h-[100px] font-mono text-xs"
                />
              </div>

              {/* Failures */}
              <div className="space-y-1">
                <label className="text-xs text-gray-500">Failures observed in this call</label>
                <textarea
                  value={row.failures}
                  onChange={(e) => updateRow(row.id, "failures", e.target.value)}
                  placeholder="e.g. Bot replied in English after the caller spoke Hindi. Bot failed to capture the caller's name correctly."
                  className="w-full rounded-lg border border-gray-200 text-sm text-gray-800 placeholder-gray-400 p-3 resize-none focus:outline-none focus:ring-2 focus:ring-blue-400 min-h-[80px]"
                />
              </div>
            </div>
          ))}
        </div>

        <div className="flex items-center justify-between">
          <button
            type="button"
            onClick={() => router.push("/intelligence")}
            className="text-sm text-gray-400 hover:text-gray-600 transition-colors"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={submitting}
            className="px-6 py-2.5 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50 transition-colors"
          >
            {submitting ? "Importing…" : "Import bot"}
          </button>
        </div>
      </form>
    </div>
  );
}
