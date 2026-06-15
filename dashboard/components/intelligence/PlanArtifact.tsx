"use client";

import { useEffect, useState } from "react";
import { Card } from "@/components/Card";
import {
  RiArrowDownSLine,
  RiArrowUpSLine,
  RiFileCopyLine,
  RiCheckLine,
} from "react-icons/ri";

export interface PlanArtifactProps {
  plan: Record<string, unknown> | null;
  planId: string | null;
  version: number | null;
  diff: Record<string, { before: unknown; after: unknown }> | null;
}

type Patch = {
  id: string;
  version: number;
  admin_request: string;
  llm_reasoning: string;
  created_at: string;
};

type HistoryEntry = {
  version: number;
  request: string;
  reasoning: string;
  date: string;
  initial: boolean;
};

type WorkflowStage = {
  stage_id: string | number;
  name: string;
  node_type: string;
  purpose: string;
  chat360_config: unknown;
};

// ── Section content renderers ──────────────────────────────────────────────────

function WorkflowBlueprintContent({ value }: { value: unknown }) {
  const bp = value as { description?: string; stages?: WorkflowStage[] } | null;
  if (!bp) return null;
  return (
    <div className="px-5 py-4 space-y-3 bg-white">
      {bp.description && <p className="text-sm text-gray-700">{bp.description}</p>}
      {bp.stages && bp.stages.length > 0 && (
        <ol className="space-y-2.5">
          {bp.stages.map((s, i) => (
            <li key={s.stage_id ?? i} className="flex items-start gap-2.5">
              <span className="mt-0.5 w-5 h-5 shrink-0 rounded-full bg-blue-50 text-blue-600 text-xs font-semibold flex items-center justify-center">
                {i + 1}
              </span>
              <div className="min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-sm font-medium text-gray-800">{s.name}</span>
                  {s.node_type && (
                    <span className="text-[10px] font-mono uppercase tracking-wide px-1.5 py-0.5 bg-gray-100 text-gray-500 rounded">
                      {s.node_type}
                    </span>
                  )}
                </div>
                {s.purpose && <p className="text-xs text-gray-500 mt-0.5">{s.purpose}</p>}
              </div>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

function SystemPromptContent({ value }: { value: unknown }) {
  const [copied, setCopied] = useState(false);
  const text = typeof value === "string" ? value : JSON.stringify(value, null, 2);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard unavailable */
    }
  };

  return (
    <div className="relative bg-white">
      <button
        onClick={copy}
        title="Copy system prompt"
        className="absolute top-3 right-3 flex items-center gap-1 px-2 py-1 text-xs font-medium rounded-md bg-gray-100 text-gray-500 hover:bg-gray-200 hover:text-gray-700 transition-colors"
      >
        {copied ? (
          <>
            <RiCheckLine className="w-3.5 h-3.5 text-emerald-500" /> Copied
          </>
        ) : (
          <>
            <RiFileCopyLine className="w-3.5 h-3.5" /> Copy
          </>
        )}
      </button>
      <pre className="px-5 py-4 pr-20 text-xs text-gray-600 overflow-x-auto whitespace-pre-wrap break-words font-mono leading-relaxed">
        {text}
      </pre>
    </div>
  );
}

function QualificationQuestionsContent({ value }: { value: unknown }) {
  const items = (value as { question?: string; variable?: string; purpose?: string }[]) ?? [];
  return (
    <div className="px-5 py-4 space-y-3 bg-white">
      {items.map((q, i) => (
        <div key={i} className="space-y-1">
          <p className="text-sm font-medium text-gray-800">{q.question}</p>
          <div className="flex items-center gap-2 flex-wrap text-xs">
            {q.variable && (
              <span className="font-mono px-1.5 py-0.5 bg-blue-50 text-blue-600 rounded">
                {q.variable}
              </span>
            )}
            {q.purpose && <span className="text-gray-500">{q.purpose}</span>}
          </div>
        </div>
      ))}
    </div>
  );
}

function ObjectionHandlingContent({ value }: { value: unknown }) {
  const entries = Object.entries((value as Record<string, string>) ?? {});
  return (
    <div className="px-5 py-4 space-y-3 bg-white">
      {entries.map(([objection, response]) => (
        <div key={objection}>
          <p className="text-sm font-medium text-gray-800">{objection}</p>
          <p className="text-sm text-gray-600 mt-1 pl-3 border-l-2 border-gray-200">
            {String(response)}
          </p>
        </div>
      ))}
    </div>
  );
}

function EscalationRulesContent({ value }: { value: unknown }) {
  const rules = (value as { trigger?: string; action?: string; node_type?: string }[]) ?? [];
  return (
    <div className="px-5 py-4 space-y-2.5 bg-white">
      {rules.map((r, i) => (
        <div key={i} className="rounded-lg border border-gray-100 p-3">
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-medium text-gray-800">{r.trigger}</p>
            {r.node_type && (
              <span className="text-[10px] font-mono uppercase tracking-wide px-1.5 py-0.5 bg-gray-100 text-gray-500 rounded shrink-0">
                {r.node_type}
              </span>
            )}
          </div>
          {r.action && <p className="text-xs text-gray-500 mt-1">→ {r.action}</p>}
        </div>
      ))}
    </div>
  );
}

function KbScaffoldContent({ value }: { value: unknown }) {
  const entries = Object.entries((value as Record<string, unknown>) ?? {});
  return (
    <div className="px-5 py-4 space-y-3 bg-white">
      {entries.map(([topic, content]) => (
        <div key={topic}>
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1">
            {topic}
          </p>
          <p className="text-sm text-gray-700 whitespace-pre-wrap">
            {typeof content === "string" ? content : JSON.stringify(content, null, 2)}
          </p>
        </div>
      ))}
    </div>
  );
}

function Chips({ items }: { items: unknown }) {
  const arr = Array.isArray(items) ? items : [];
  if (arr.length === 0) return null;
  return (
    <div className="flex flex-wrap gap-1.5">
      {arr.map((v, i) => (
        <span
          key={i}
          className="font-mono text-xs px-1.5 py-0.5 bg-gray-100 text-gray-600 rounded"
        >
          {String(v)}
        </span>
      ))}
    </div>
  );
}

function BuildNotesContent({ value }: { value: unknown }) {
  const bn = (value as Record<string, unknown>) ?? {};
  const instructions = Array.isArray(bn.canvas_instructions) ? bn.canvas_instructions : [];
  const knownKeys = new Set([
    "canvas_instructions",
    "variables_required",
    "outbound_params",
    "tts_engine",
    "stt_engine",
    "language",
  ]);
  const rest = Object.fromEntries(Object.entries(bn).filter(([k]) => !knownKeys.has(k)));

  const Field = ({ label, val }: { label: string; val: unknown }) =>
    val ? (
      <div className="flex items-center gap-2">
        <span className="text-xs text-gray-400">{label}</span>
        <span className="text-xs font-medium text-gray-700">{String(val)}</span>
      </div>
    ) : null;

  return (
    <div className="px-5 py-4 space-y-4 bg-white">
      {instructions.length > 0 && (
        <div className="space-y-1.5">
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
            Canvas instructions
          </p>
          <ol className="space-y-1">
            {instructions.map((step, i) => (
              <li key={i} className="text-sm text-gray-700 flex items-start gap-1.5">
                <span className="text-blue-500 font-semibold shrink-0">{i + 1}.</span>
                <span>{String(step)}</span>
              </li>
            ))}
          </ol>
        </div>
      )}

      {Boolean(bn.tts_engine || bn.stt_engine || bn.language) && (
        <div className="flex flex-wrap gap-4">
          <Field label="TTS" val={bn.tts_engine} />
          <Field label="STT" val={bn.stt_engine} />
          <Field label="Language" val={bn.language} />
        </div>
      )}

      {Array.isArray(bn.variables_required) && bn.variables_required.length > 0 && (
        <div className="space-y-1">
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
            Variables required
          </p>
          <Chips items={bn.variables_required} />
        </div>
      )}

      {Array.isArray(bn.outbound_params) && bn.outbound_params.length > 0 && (
        <div className="space-y-1">
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
            Outbound params
          </p>
          <Chips items={bn.outbound_params} />
        </div>
      )}

      {Object.keys(rest).length > 0 && (
        <pre className="text-xs text-gray-500 bg-gray-50 rounded-lg p-3 overflow-x-auto whitespace-pre-wrap break-words">
          {JSON.stringify(rest, null, 2)}
        </pre>
      )}
    </div>
  );
}

function GenericContent({ value }: { value: unknown }) {
  return (
    <pre className="px-5 py-4 text-xs text-gray-600 bg-white overflow-x-auto whitespace-pre-wrap break-words">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

function DiffPanel({ before, after }: { before: unknown; after: unknown }) {
  return (
    <div className="mx-5 mb-4 space-y-1">
      <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide">Diff</p>
      <div className="grid grid-cols-2 gap-2 text-xs">
        <div className="bg-red-50 border border-red-100 rounded p-2 text-red-700 font-mono whitespace-pre-wrap break-words">
          {JSON.stringify(before, null, 2)}
        </div>
        <div className="bg-emerald-50 border border-emerald-100 rounded p-2 text-emerald-700 font-mono whitespace-pre-wrap break-words">
          {JSON.stringify(after, null, 2)}
        </div>
      </div>
    </div>
  );
}

// ── Section wrapper ─────────────────────────────────────────────────────────────

interface SectionProps {
  sectionKey: string;
  title: string;
  value: unknown;
  diff: Record<string, { before: unknown; after: unknown }> | null;
  flashedKeys: Set<string>;
}

function Section({ sectionKey, title, value, diff, flashedKeys }: SectionProps) {
  const [open, setOpen] = useState(false);
  if (value == null || (Array.isArray(value) && value.length === 0)) return null;

  const hasChange = diff != null && sectionKey in diff;
  const isFlashing = flashedKeys.has(sectionKey);

  const renderContent = () => {
    switch (sectionKey) {
      case "workflow_blueprint":
        return <WorkflowBlueprintContent value={value} />;
      case "system_prompt":
        return <SystemPromptContent value={value} />;
      case "qualification_questions":
        return <QualificationQuestionsContent value={value} />;
      case "objection_handling":
        return <ObjectionHandlingContent value={value} />;
      case "escalation_rules":
        return <EscalationRulesContent value={value} />;
      case "kb_scaffold":
        return <KbScaffoldContent value={value} />;
      case "build_notes":
        return <BuildNotesContent value={value} />;
      default:
        return <GenericContent value={value} />;
    }
  };

  return (
    <div
      className={`border border-gray-100 rounded-xl overflow-hidden ${
        isFlashing ? "flash-row" : ""
      }`}
    >
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between px-5 py-3 text-sm font-semibold text-gray-700 bg-gray-50 hover:bg-gray-100 transition-colors"
      >
        <span className="flex items-center gap-2">
          {title}
          {hasChange && (
            <span className="text-xs font-medium px-1.5 py-0.5 bg-amber-100 text-amber-700 rounded-full">
              changed
            </span>
          )}
        </span>
        {open ? (
          <RiArrowUpSLine className="w-4 h-4 text-gray-400 shrink-0" />
        ) : (
          <RiArrowDownSLine className="w-4 h-4 text-gray-400 shrink-0" />
        )}
      </button>
      {open && (
        <>
          {renderContent()}
          {hasChange && diff && (
            <DiffPanel before={diff[sectionKey].before} after={diff[sectionKey].after} />
          )}
        </>
      )}
    </div>
  );
}

// ── Main component ──────────────────────────────────────────────────────────────

export default function PlanArtifact({ plan, planId, version, diff }: PlanArtifactProps) {
  const [tab, setTab] = useState<"current" | "history">("current");
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [flashedKeys, setFlashedKeys] = useState<Set<string>>(new Set());

  // Flash changed sections for 2s when diff changes
  useEffect(() => {
    if (!diff || Object.keys(diff).length === 0) return;
    setFlashedKeys(new Set(Object.keys(diff)));
    const timer = setTimeout(() => setFlashedKeys(new Set()), 2000);
    return () => clearTimeout(timer);
  }, [diff]);

  // Build version timeline: patches (v2+) + a synthesized v1 (initial generation)
  useEffect(() => {
    if (!planId || tab !== "history") return;
    setHistoryLoading(true);
    Promise.all([
      fetch(`/api/intelligence/plans/${planId}`).then((r) => r.json()),
      fetch(`/api/intelligence/plans/${planId}/patches`).then((r) => r.json()),
    ])
      .then(([planRow, patchRows]) => {
        const patches: Patch[] = Array.isArray(patchRows) ? patchRows : [];
        const entries: HistoryEntry[] = patches.map((pt) => ({
          version: pt.version,
          request: pt.admin_request,
          reasoning: pt.llm_reasoning,
          date: pt.created_at,
          initial: false,
        }));
        // Synthesize the v1 entry — initial generation never writes a patch row
        entries.push({
          version: 1,
          request: "Initial plan generated",
          reasoning: "",
          date: planRow?.created_at ?? "",
          initial: true,
        });
        entries.sort((a, b) => b.version - a.version);
        setHistory(entries);
      })
      .catch(() => setHistory([]))
      .finally(() => setHistoryLoading(false));
  }, [planId, tab]);

  const SECTIONS: { key: string; title: string }[] = [
    { key: "workflow_blueprint", title: "Workflow Blueprint" },
    { key: "system_prompt", title: "System Prompt" },
    { key: "qualification_questions", title: "Qualification Questions" },
    { key: "objection_handling", title: "Objection Handling" },
    { key: "escalation_rules", title: "Escalation Rules" },
    { key: "kb_scaffold", title: "KB Scaffold" },
    { key: "build_notes", title: "Build Notes" },
  ];

  return (
    <Card className="flex flex-col p-0 overflow-hidden min-h-150">
      {/* Header */}
      <div className="px-5 pt-4 pb-2 flex items-center justify-between border-b border-gray-100">
        <div>
          <p className="text-base font-semibold text-gray-800">
            {version != null ? `Plan v${version}` : "No plan yet"}
          </p>
          {planId && <p className="text-xs text-gray-400 mt-0.5 font-mono">{planId}</p>}
        </div>
        {/* Segmented toggle */}
        <div className="flex bg-gray-100 rounded-lg p-0.5 gap-0.5">
          {(["current", "history"] as const).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`px-3 py-1 text-xs font-medium rounded-md transition-colors ${
                tab === t
                  ? "bg-white text-gray-800 shadow-sm"
                  : "text-gray-500 hover:text-gray-700"
              }`}
            >
              {t.charAt(0).toUpperCase() + t.slice(1)}
            </button>
          ))}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto">
        {tab === "current" && (
          <div className="p-5 space-y-2">
            {!plan && (
              <p className="text-sm text-gray-400 text-center pt-12">
                Start chatting to generate a plan
              </p>
            )}
            {plan &&
              SECTIONS.map(({ key, title }) => (
                <Section
                  key={key}
                  sectionKey={key}
                  title={title}
                  value={plan[key]}
                  diff={diff}
                  flashedKeys={flashedKeys}
                />
              ))}
          </div>
        )}

        {tab === "history" && (
          <div className="p-5">
            {!planId && (
              <p className="text-sm text-gray-400 text-center pt-12">No plan loaded yet</p>
            )}
            {planId && historyLoading && (
              <p className="text-sm text-gray-400 text-center pt-12">Loading history…</p>
            )}
            {planId && !historyLoading && history.length > 0 && (
              <div className="space-y-3">
                {history.map((h) => (
                  <div key={h.version} className="border-l-2 border-blue-200 pl-4">
                    <p className="text-xs text-gray-400 flex items-center gap-2">
                      <span className="font-semibold text-gray-600">v{h.version}</span>
                      {h.date && <span>{h.date.slice(0, 10)}</span>}
                      {h.initial && (
                        <span className="text-[10px] font-medium px-1.5 py-0.5 bg-blue-50 text-blue-600 rounded-full">
                          initial
                        </span>
                      )}
                    </p>
                    <p className="text-sm text-gray-700 font-medium mt-0.5">{h.request}</p>
                    {h.reasoning && (
                      <p className="text-xs text-gray-400 mt-0.5">{h.reasoning}</p>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </Card>
  );
}
