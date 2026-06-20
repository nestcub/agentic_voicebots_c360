"use client";

import { useEffect, useRef, useState } from "react";

const INTEL_URL = process.env.NEXT_PUBLIC_INTEL_API_URL ?? "http://localhost:8001";
const INTEL_KEY = process.env.NEXT_PUBLIC_INTEL_API_KEY ?? "";

const h = () => ({ "x-api-key": INTEL_KEY, "Content-Type": "application/json" });
const hGet = () => ({ "x-api-key": INTEL_KEY });

type ChatMsg = { role: "user" | "assistant"; content: string };
type InsightRow = {
  id: string;
  raw_insights_json: {
    user_reported_failures?: string;
    bot_failure_modes?: string[];
    suggested_fixes?: string[];
    summary?: string;
  } | null;
};

export default function ImportedBuild({ clientId }: { clientId: string }) {
  const [botName, setBotName]         = useState("");
  const [systemPrompt, setSystemPrompt] = useState("");
  const [status, setStatus]           = useState("");
  const [transcripts, setTranscripts] = useState<{ id: string; filename: string }[]>([]);
  const [insights, setInsights]       = useState<Record<string, InsightRow>>({});
  const [messages, setMessages]       = useState<ChatMsg[]>([]);
  const [input, setInput]             = useState("");
  const [sending, setSending]         = useState(false);
  const [chatError, setChatError]     = useState("");
  const [loading, setLoading]         = useState(true);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    async function load() {
      try {
        // Load imported bot status (name + system prompt)
        const r = await fetch(`${INTEL_URL}/bots/import/${clientId}/status`, { headers: hGet() });
        if (r.ok) {
          const d = await r.json();
          setBotName(d.bot_name ?? "");
          setSystemPrompt(d.system_prompt ?? "");
          setStatus(d.status ?? "");
        }
        // Load transcripts
        const tr = await fetch(`${INTEL_URL}/transcripts?client_id=${encodeURIComponent(clientId)}`, { headers: hGet() });
        if (tr.ok) {
          const tdata = await tr.json();
          const tlist: { id: string; filename: string }[] = (tdata ?? []).map((t: { id: string; filename: string }) => ({ id: t.id, filename: t.filename }));
          setTranscripts(tlist);
          // Load insights per transcript
          const insightMap: Record<string, InsightRow> = {};
          await Promise.all(
            tlist.map(async (t) => {
              try {
                const ir = await fetch(`${INTEL_URL}/transcripts/${t.id}/insights`, { headers: hGet() });
                if (ir.ok) {
                  const idata = await ir.json();
                  insightMap[t.id] = idata;
                }
              } catch { /* ignore per-transcript failures */ }
            })
          );
          setInsights(insightMap);
        }
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [clientId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function sendMessage() {
    const text = input.trim();
    if (!text || sending) return;
    setInput("");
    setSending(true);
    setChatError("");
    setMessages((prev) => [...prev, { role: "user", content: text }]);
    try {
      const res = await fetch(`${INTEL_URL}/imported/chat`, {
        method: "POST",
        headers: h(),
        body: JSON.stringify({ client_id: clientId, message: text }),
      });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        throw new Error(d.detail || `Error ${res.status}`);
      }
      const data = await res.json();
      setMessages((prev) => [...prev, { role: "assistant", content: data.reply ?? "" }]);
    } catch (err) {
      setChatError(err instanceof Error ? err.message : "Chat failed.");
    } finally {
      setSending(false);
    }
  }

  if (loading) {
    return (
      <div className="space-y-3 animate-pulse">
        <div className="h-6 bg-gray-100 rounded w-1/3" />
        <div className="h-40 bg-gray-100 rounded" />
      </div>
    );
  }

  void status;

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-base font-semibold text-gray-800">{botName || "Imported bot"}</h2>
        <span className="text-xs bg-purple-100 text-purple-700 px-2 py-0.5 rounded-full font-medium">imported</span>
      </div>

      <div className="grid lg:grid-cols-[1fr_1.2fr] gap-6 items-start">
        {/* Left — Chat */}
        <div className="bg-white border border-gray-200 rounded-xl flex flex-col" style={{ minHeight: "520px" }}>
          <div className="px-4 py-3 border-b border-gray-100">
            <p className="text-sm font-medium text-gray-700">Test this prompt</p>
            <p className="text-xs text-gray-400">Ask whether the prompt handles specific failures</p>
          </div>

          <div className="flex-1 overflow-y-auto p-4 space-y-3">
            {messages.length === 0 && (
              <p className="text-xs text-gray-400 text-center py-8">
                Ask something like &ldquo;Does this prompt prevent the bot replying in English to a Hindi caller?&rdquo;
              </p>
            )}
            {messages.map((m, i) => (
              <div key={i} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
                <div
                  className={`max-w-[85%] rounded-xl px-3 py-2 text-sm whitespace-pre-wrap ${
                    m.role === "user"
                      ? "bg-blue-600 text-white"
                      : "bg-gray-100 text-gray-800"
                  }`}
                >
                  {m.content}
                </div>
              </div>
            ))}
            {sending && (
              <div className="flex justify-start">
                <div className="bg-gray-100 rounded-xl px-3 py-2 text-sm text-gray-400 flex items-center gap-1.5">
                  <span className="w-3 h-3 border-2 border-gray-400 border-t-transparent rounded-full animate-spin" />
                  Thinking…
                </div>
              </div>
            )}
            {chatError && (
              <p className="text-xs text-red-500 text-center">{chatError}</p>
            )}
            <div ref={bottomRef} />
          </div>

          <div className="p-3 border-t border-gray-100 flex gap-2">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(); } }}
              placeholder="Ask about the prompt…"
              className="flex-1 rounded-lg border border-gray-200 text-sm px-3 py-2 resize-none focus:outline-none focus:ring-2 focus:ring-blue-400 min-h-[40px] max-h-[120px]"
              rows={1}
            />
            <button
              onClick={sendMessage}
              disabled={sending || !input.trim()}
              className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-40 transition-colors shrink-0"
            >
              Send
            </button>
          </div>
        </div>

        {/* Right — Context panel */}
        <div className="space-y-4">
          {/* System prompt */}
          <div className="bg-white border border-gray-200 rounded-xl p-4 space-y-2">
            <p className="text-sm font-semibold text-gray-700">System prompt under test</p>
            {systemPrompt ? (
              <pre className="text-xs text-gray-600 bg-gray-50 rounded-lg p-3 overflow-y-auto max-h-64 whitespace-pre-wrap break-words font-mono">
                {systemPrompt}
              </pre>
            ) : (
              <p className="text-xs text-gray-400">No system prompt stored.</p>
            )}
          </div>

          {/* Failures & insights */}
          <div className="bg-white border border-gray-200 rounded-xl p-4 space-y-3">
            <p className="text-sm font-semibold text-gray-700">Observed failures &amp; insights</p>
            {transcripts.length === 0 ? (
              <p className="text-xs text-gray-400">No transcripts uploaded.</p>
            ) : (
              transcripts.map((t) => {
                const ins = insights[t.id];
                const raw = ins?.raw_insights_json;
                return (
                  <div key={t.id} className="border border-gray-100 rounded-lg p-3 space-y-2 bg-gray-50">
                    <p className="text-xs font-medium text-gray-600 truncate">{t.filename}</p>
                    {raw?.user_reported_failures && (
                      <div>
                        <p className="text-xs font-semibold text-red-600 mb-0.5">Reported failures</p>
                        <p className="text-xs text-gray-700 whitespace-pre-wrap">{raw.user_reported_failures}</p>
                      </div>
                    )}
                    {raw?.bot_failure_modes && raw.bot_failure_modes.length > 0 && (
                      <div>
                        <p className="text-xs font-semibold text-orange-600 mb-0.5">Bot failure modes</p>
                        <ul className="text-xs text-gray-700 list-disc list-inside space-y-0.5">
                          {raw.bot_failure_modes.map((f, i) => <li key={i}>{f}</li>)}
                        </ul>
                      </div>
                    )}
                    {raw?.suggested_fixes && raw.suggested_fixes.length > 0 && (
                      <div>
                        <p className="text-xs font-semibold text-green-700 mb-0.5">Suggested fixes</p>
                        <ul className="text-xs text-gray-700 list-disc list-inside space-y-0.5">
                          {raw.suggested_fixes.map((f, i) => <li key={i}>{f}</li>)}
                        </ul>
                      </div>
                    )}
                    {raw?.summary && (
                      <p className="text-xs text-gray-500 italic">{raw.summary}</p>
                    )}
                    {!raw && <p className="text-xs text-gray-400">No insights yet.</p>}
                  </div>
                );
              })
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
