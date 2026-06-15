"use client";

import { useEffect, useRef, useState } from "react";
import { Card, CardHeader } from "@/components/Card";
import { RiSendPlaneLine, RiRobot2Line, RiUserLine } from "react-icons/ri";

type Turn = { role: "user" | "assistant"; content: string };

export interface ChatThreadProps {
  clientId: string;
  onPlanUpdate: (data: {
    plan: Record<string, unknown> | null;
    plan_id: string | null;
    diff: Record<string, { before: unknown; after: unknown }> | null;
    version: number | null;
    plan_changed: boolean;
    mode: string;
  }) => void;
}

export default function ChatThread({ clientId, onPlanUpdate }: ChatThreadProps) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns, loading]);

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
      setTurns((t) => [
        ...t,
        { role: "assistant", content: data.reply ?? JSON.stringify(data) },
      ]);
      onPlanUpdate({
        plan: data.plan ?? null,
        plan_id: data.plan_id ?? null,
        diff: data.diff ?? null,
        version: data.version ?? null,
        plan_changed: data.plan_changed ?? false,
        mode: data.mode ?? "",
      });
    } catch {
      setTurns((t) => [
        ...t,
        {
          role: "assistant",
          content: "Request failed. Is the intelligence server running?",
        },
      ]);
    }
    setLoading(false);
  }

  return (
    <Card className="flex flex-col p-0 overflow-hidden h-[600px]">
      <CardHeader
        title="Chat"
        hint={clientId ? `client: ${clientId}` : "no client set"}
      />

      {!clientId && (
        <div className="mx-5 mb-2 p-3 bg-amber-50 border border-amber-200 rounded-lg text-sm text-amber-700">
          No Client ID set.{" "}
          <a href="/intelligence" className="underline font-medium">
            Set one on the hub.
          </a>
        </div>
      )}

      <div className="flex-1 overflow-y-auto px-5 py-3 space-y-4">
        {turns.length === 0 && (
          <p className="text-sm text-gray-400 text-center pt-16">
            Describe your use case to get started…
          </p>
        )}
        {turns.map((t, i) => (
          <div
            key={i}
            className={`flex gap-3 ${t.role === "user" ? "flex-row-reverse" : ""}`}
          >
            <div
              className={`w-7 h-7 rounded-full flex items-center justify-center shrink-0 ${
                t.role === "user" ? "bg-blue-600" : "bg-gray-100"
              }`}
            >
              {t.role === "user" ? (
                <RiUserLine className="w-4 h-4 text-white" />
              ) : (
                <RiRobot2Line className="w-4 h-4 text-gray-500" />
              )}
            </div>
            <div
              className={`max-w-[80%] px-4 py-2.5 rounded-xl text-sm ${
                t.role === "user"
                  ? "bg-blue-600 text-white"
                  : "bg-gray-100 text-gray-800"
              }`}
            >
              {t.content}
            </div>
          </div>
        ))}
        {loading && (
          <div className="flex gap-3">
            <div className="w-7 h-7 rounded-full bg-gray-100 flex items-center justify-center">
              <RiRobot2Line className="w-4 h-4 text-gray-400 animate-pulse" />
            </div>
            <div className="bg-gray-100 px-4 py-2.5 rounded-xl text-sm text-gray-400">
              Thinking…
            </div>
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
          disabled={!clientId}
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
  );
}
