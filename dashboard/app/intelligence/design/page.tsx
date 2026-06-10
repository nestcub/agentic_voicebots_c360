"use client";

import { useEffect, useRef, useState } from "react";
import { Card, CardHeader } from "@/components/Card";
import { RiSendPlaneLine, RiRobot2Line, RiUserLine } from "react-icons/ri";

type Turn = { role: "user" | "assistant"; content: string };
type Diff = Record<string, { before: unknown; after: unknown }>;
type PlanSummary = { description?: string; stages?: { name: string }[]; system_prompt?: string };

export default function DesignPage() {
  const [clientId, setClientId] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);
  const [diff, setDiff] = useState<Diff | null>(null);
  const [plan, setPlan] = useState<PlanSummary | null>(null);
  const [planVersion, setPlanVersion] = useState<number | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setClientId(localStorage.getItem("intel_client_id") ?? "");
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns]);

  async function send() {
    if (!message.trim() || !clientId || loading) return;
    const userMsg = message.trim();
    setMessage("");
    setTurns((t) => [...t, { role: "user", content: userMsg }]);
    setLoading(true);
    try {
      const res = await fetch("/api/intelligence/converse", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ client_id: clientId, message: userMsg }),
      });
      const data = await res.json();
      setTurns((t) => [...t, { role: "assistant", content: data.reply ?? JSON.stringify(data) }]);
      if (data.plan_changed && data.diff) setDiff(data.diff);
      if (data.plan) {
        const bp = data.plan.workflow_blueprint ?? {};
        setPlan({ description: bp.description, stages: bp.stages, system_prompt: data.plan.system_prompt });
        setPlanVersion(data.version ?? null);
      }
    } catch (e) {
      setTurns((t) => [...t, { role: "assistant", content: "Request failed. Is the intelligence server running?" }]);
    }
    setLoading(false);
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-lg font-semibold text-gray-800">Workflow Designer</h1>
        <p className="text-xs text-gray-400 mt-0.5">Conversational AI that builds and refines your Chat360 workflow plan</p>
      </div>

      {!clientId && (
        <div className="p-4 bg-amber-50 border border-amber-200 rounded-xl text-sm text-amber-700">
          No Client ID set. <a href="/intelligence" className="underline font-medium">Set one on the hub.</a>
        </div>
      )}

      <div className="grid md:grid-cols-3 gap-6">
        {/* Chat */}
        <div className="md:col-span-2 flex flex-col gap-4">
          <Card className="flex flex-col p-0 overflow-hidden" style={{ height: "520px" }}>
            <CardHeader title="Chat" hint={clientId ? `client: ${clientId}` : "no client set"} />
            <div className="flex-1 overflow-y-auto px-5 py-3 space-y-4">
              {turns.length === 0 && (
                <p className="text-sm text-gray-400 text-center pt-16">Describe your use case to get started…</p>
              )}
              {turns.map((t, i) => (
                <div key={i} className={`flex gap-3 ${t.role === "user" ? "flex-row-reverse" : ""}`}>
                  <div className={`w-7 h-7 rounded-full flex items-center justify-center shrink-0 ${t.role === "user" ? "bg-blue-600" : "bg-gray-100"}`}>
                    {t.role === "user" ? <RiUserLine className="w-4 h-4 text-white" /> : <RiRobot2Line className="w-4 h-4 text-gray-500" />}
                  </div>
                  <div className={`max-w-[80%] px-4 py-2.5 rounded-xl text-sm ${t.role === "user" ? "bg-blue-600 text-white" : "bg-gray-100 text-gray-800"}`}>
                    {t.content}
                  </div>
                </div>
              ))}
              {loading && (
                <div className="flex gap-3">
                  <div className="w-7 h-7 rounded-full bg-gray-100 flex items-center justify-center">
                    <RiRobot2Line className="w-4 h-4 text-gray-400 animate-pulse" />
                  </div>
                  <div className="bg-gray-100 px-4 py-2.5 rounded-xl text-sm text-gray-400">Thinking…</div>
                </div>
              )}
              <div ref={bottomRef} />
            </div>
            <div className="border-t border-gray-100 p-4 flex gap-3">
              <input
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && send()}
                placeholder="Describe your workflow or request a change…"
                className="flex-1 px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
              <button
                onClick={send}
                disabled={loading || !message.trim() || !clientId}
                className="p-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-40 transition-colors"
              >
                <RiSendPlaneLine className="w-5 h-5" />
              </button>
            </div>
          </Card>

          {/* Diff panel */}
          {diff && Object.keys(diff).length > 0 && (
            <Card className="p-5 space-y-3">
              <CardHeader title="Plan changes" hint="what the last message updated" />
              {Object.entries(diff).map(([key, { before, after }]) => (
                <div key={key}>
                  <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1">{key}</p>
                  <div className="grid grid-cols-2 gap-2 text-xs">
                    <div className="bg-red-50 border border-red-100 rounded p-2 text-red-700 font-mono whitespace-pre-wrap break-all">{JSON.stringify(before, null, 2)}</div>
                    <div className="bg-emerald-50 border border-emerald-100 rounded p-2 text-emerald-700 font-mono whitespace-pre-wrap break-all">{JSON.stringify(after, null, 2)}</div>
                  </div>
                </div>
              ))}
            </Card>
          )}
        </div>

        {/* Plan summary */}
        <div>
          <Card className="p-5 space-y-4 sticky top-20">
            <CardHeader title="Current Plan" hint={planVersion != null ? `v${planVersion}` : "none yet"} />
            {!plan && <p className="text-sm text-gray-400">No plan generated yet.</p>}
            {plan && (
              <div className="space-y-3">
                {plan.description && (
                  <div>
                    <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1">Description</p>
                    <p className="text-sm text-gray-700">{plan.description}</p>
                  </div>
                )}
                {plan.stages && plan.stages.length > 0 && (
                  <div>
                    <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1">Stages ({plan.stages.length})</p>
                    <ol className="space-y-1">
                      {plan.stages.map((s, i) => (
                        <li key={i} className="text-sm text-gray-700 flex items-start gap-1.5">
                          <span className="text-blue-500 font-semibold shrink-0">{i + 1}.</span>{s.name}
                        </li>
                      ))}
                    </ol>
                  </div>
                )}
                <a href="/intelligence/plans" className="text-xs text-blue-600 hover:underline">View full plan →</a>
              </div>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}
