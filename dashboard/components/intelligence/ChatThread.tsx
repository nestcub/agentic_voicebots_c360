"use client";

import React, { useEffect, useRef, useState } from "react";
import { Card, CardHeader } from "@/components/Card";
import { RiSendPlaneLine, RiRobot2Line, RiUserLine } from "react-icons/ri";

type Turn = { role: "user" | "assistant"; content: string };

function safeParseJson(value: string): unknown | null {
  if (!value) return null;
  try {
    return JSON.parse(value);
  } catch {
    return null;
  }
}

function extractErrorMessage(payload: unknown, fallback: string): string {
  if (typeof payload === "string" && payload.trim()) return payload.trim();

  if (payload && typeof payload === "object") {
    const record = payload as Record<string, unknown>;
    const candidates = [
      record.message,
      record.error,
      record.detail,
      record.details,
    ];

    for (const candidate of candidates) {
      if (typeof candidate === "string" && candidate.trim()) {
        return candidate.trim();
      }

      if (candidate && typeof candidate === "object") {
        const nested = extractErrorMessage(candidate, "");
        if (nested) return nested;
      }
    }
  }

  return fallback;
}

function formatAssistantError(status: number | null, message: string): string {
  const prefix = status ? `Request failed (${status})` : "Request failed";
  return `${prefix}: ${message}`;
}

function renderInline(text: string): React.ReactNode {
  // Handle **bold**
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  return parts.map((part, i) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return <strong key={i} className="font-semibold">{part.slice(2, -2)}</strong>;
    }
    return part;
  });
}

function MarkdownContent({ text }: { text: string }) {
  const lines = text.split("\n");
  const elements: React.ReactNode[] = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    if (line.startsWith("### ")) {
      elements.push(<h3 key={i} className="text-sm font-bold text-gray-800 mt-3 mb-1">{line.slice(4)}</h3>);
    } else if (line.startsWith("## ")) {
      elements.push(<h2 key={i} className="text-sm font-bold text-gray-900 mt-4 mb-1 border-b border-gray-200 pb-1">{line.slice(3)}</h2>);
    } else if (line.startsWith("---")) {
      elements.push(<hr key={i} className="border-gray-200 my-2" />);
    } else if (line.startsWith("- ") || line.startsWith("* ")) {
      // collect consecutive list items
      const items: string[] = [];
      while (i < lines.length && (lines[i].startsWith("- ") || lines[i].startsWith("* "))) {
        items.push(lines[i].slice(2));
        i++;
      }
      elements.push(
        <ul key={`ul-${i}`} className="list-disc list-inside space-y-0.5 my-1 text-gray-700">
          {items.map((item, j) => <li key={j} className="text-sm">{renderInline(item)}</li>)}
        </ul>
      );
      continue;
    } else if (line.trim() === "") {
      // skip blank lines between blocks
    } else {
      elements.push(<p key={i} className="text-sm text-gray-800 leading-relaxed">{renderInline(line)}</p>);
    }
    i++;
  }

  return <div className="space-y-1">{elements}</div>;
}

function isMarkdown(text: string): boolean {
  return /^#{1,3} |^\- |\*\*|^---/m.test(text);
}

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
  const [intentAware, setIntentAware] = useState(true);
  const [showIntentInfo, setShowIntentInfo] = useState(false);
  const [model, setModel] = useState<"sonnet" | "gpt-4.1">("sonnet");
  const providerMap: Record<string, string> = { "sonnet": "anthropic", "gpt-4.1": "openai" };
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
        body: JSON.stringify({
          client_id: clientId,
          message: userMsg,
          intent_aware: intentAware,
          provider: providerMap[model],
        }),
      });

      const raw = await res.text();
      const data = safeParseJson(raw);

      if (!res.ok) {
        const message = extractErrorMessage(
          data ?? raw,
          "The intelligence service returned an error.",
        );
        setTurns((t) => [
          ...t,
          {
            role: "assistant",
            content: formatAssistantError(res.status, message),
          },
        ]);
        return;
      }

      setTurns((t) => [
        ...t,
        {
          role: "assistant",
          content:
            data && typeof data === "object" && "reply" in data
              ? String((data as { reply?: unknown }).reply ?? "")
              : raw,
        },
      ]);

      const response =
        data && typeof data === "object"
          ? (data as Record<string, unknown>)
          : {};

      onPlanUpdate({
        plan: (response.plan as Record<string, unknown> | null | undefined) ?? null,
        plan_id: (response.plan_id as string | null | undefined) ?? null,
        diff:
          (response.diff as
            | Record<string, { before: unknown; after: unknown }>
            | null
            | undefined) ?? null,
        version: (response.version as number | null | undefined) ?? null,
        plan_changed: (response.plan_changed as boolean | undefined) ?? false,
        mode: (response.mode as string | undefined) ?? "",
      });
    } catch (error) {
      const message =
        error instanceof Error && error.message
          ? error.message
          : "Unable to reach the intelligence service.";
      setTurns((t) => [
        ...t,
        {
          role: "assistant",
          content: formatAssistantError(null, message),
        },
      ]);
    } finally {
      setLoading(false);
    }
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
            className={`flex flex-col ${t.role === "user" ? "items-end" : "items-start"} gap-0.5`}
          >
            <div className={`flex gap-3 ${t.role === "user" ? "flex-row-reverse" : ""}`}>
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
                {t.role === "assistant" ? (
                  isMarkdown(t.content) ? (
                    <MarkdownContent text={t.content} />
                  ) : (
                    <span className="whitespace-pre-wrap">{t.content}</span>
                  )
                ) : (
                  t.content
                )}
              </div>
            </div>
            {t.role === "assistant" && (
              <button
                onClick={() => navigator.clipboard.writeText(t.content)}
                className="mt-1 self-end text-xs text-gray-400 hover:text-gray-600 px-2 py-0.5 rounded hover:bg-gray-100 transition"
                title="Copy"
              >
                Copy
              </button>
            )}
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

      <div className="border-t border-gray-100 px-4 py-2 flex items-center gap-4 text-xs text-gray-500">
        {/* Intent-aware toggle */}
        <label className="flex items-center gap-1.5 cursor-pointer select-none">
          <input
            type="checkbox"
            checked={intentAware}
            onChange={e => setIntentAware(e.target.checked)}
            className="w-3.5 h-3.5 accent-blue-600"
          />
          <span>Smart context</span>
          <span
            className="relative cursor-help"
            onClick={() => setShowIntentInfo(v => !v)}
          >
            <span className="text-gray-400 hover:text-gray-600 text-xs border border-gray-300 rounded-full w-4 h-4 inline-flex items-center justify-center">ⓘ</span>
            {showIntentInfo && (
              <div className="absolute bottom-6 left-0 z-50 w-64 bg-white border border-gray-200 rounded-lg shadow-lg p-3 text-xs text-gray-700 leading-relaxed">
                <p className="font-semibold mb-1">Smart Context Loading</p>
                <p>When enabled, advice and KB questions skip loading your full bot plan and examples — reducing API cost. Disable if the response seems to be missing plan context.</p>
                <button onClick={() => setShowIntentInfo(false)} className="mt-2 text-blue-600 hover:underline">Close</button>
              </div>
            )}
          </span>
        </label>
        {/* Model pills */}
        <div className="flex items-center gap-1 ml-auto">
          {(["sonnet", "gpt-4.1"] as const).map(m => (
            <button
              key={m}
              onClick={() => setModel(m)}
              className={`px-2 py-0.5 rounded text-xs border transition ${
                model === m
                  ? "bg-blue-600 text-white border-blue-600"
                  : "bg-white text-gray-500 border-gray-200 hover:border-gray-400"
              }`}
            >
              {m === "sonnet" ? "Sonnet 4.6" : "GPT-4.1"}
            </button>
          ))}
        </div>
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
