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
  patch: Record<string, unknown>;
};

type HistoryEntry = {
  version: number;
  request: string;
  reasoning: string;
  date: string;
  initial: boolean;
  patch: Record<string, unknown> | null; // changed keys for patch rows; null for initial
};

const SECTION_TITLES: Record<string, string> = {
  system_prompt_sections: "System Prompt",
  workflow_blueprint: "Workflow Blueprint",
  bot_kb: "Bot Knowledge Base",
  build_notes: "Build Notes",
  // legacy keys
  system_prompt: "System Prompt",
  qualification_questions: "Qualification Questions",
  objection_handling: "Objection Handling",
  escalation_rules: "Escalation Rules",
  kb_scaffold: "KB Scaffold",
};

// ── version label helper ───────────────────────────────────────────────────────

function vLabel(v: number | null): string {
  if (v == null || v <= 1) return "V1";
  return `V1.${v - 1}`;
}

type WorkflowStage = {
  stage_id: string | number;
  name: string;
  node_type: string;
  purpose: string;
  chat360_config: unknown;
};

// ── Section content renderers ──────────────────────────────────────────────────

const SYSTEM_PROMPT_SECTION_ORDER = [
  "critical_rules", "roles", "objectives", "personality",
  "important_flow_rules", "guardrails", "instructions",
  "conversational_flow", "closure", "objection_handling",
  "conversation_example", "safety_guardrails",
];

function CopyButton({ text, size = "sm" }: { text: string; size?: "sm" | "xs" }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try { await navigator.clipboard.writeText(text); setCopied(true); setTimeout(() => setCopied(false), 1500); } catch { /* */ }
  };
  const cls = size === "xs"
    ? "flex items-center gap-1 px-1.5 py-0.5 text-[10px] font-medium rounded bg-white border border-gray-200 text-gray-400 hover:text-gray-600 hover:border-gray-300 transition-colors"
    : "flex items-center gap-1 px-2 py-1 text-xs font-medium rounded-md bg-white border border-gray-200 text-gray-500 hover:bg-gray-50 transition-colors";
  return (
    <button onClick={copy} className={cls}>
      {copied ? <><RiCheckLine className="w-3 h-3 text-emerald-500" />Copied</> : <><RiFileCopyLine className="w-3 h-3" />Copy</>}
    </button>
  );
}

function SystemPromptSectionsContent({ value }: { value: unknown }) {
  const sections = (value as Record<string, string>) ?? {};
  const toLabel = (k: string) =>
    k.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

  const ordered = SYSTEM_PROMPT_SECTION_ORDER
    .filter((k) => sections[k] != null && String(sections[k]).trim() !== "")
    .map((k) => [k, sections[k]] as [string, string]);
  const knownKeys = new Set(SYSTEM_PROMPT_SECTION_ORDER);
  const extra = Object.entries(sections).filter(
    ([k, v]) => !knownKeys.has(k) && v != null && String(v).trim() !== ""
  ) as [string, string][];
  const all = [...ordered, ...extra];

  const allText = all.map(([k, t]) => `## ${toLabel(k)}\n${t}`).join("\n\n");

  return (
    <div className="px-5 py-4 space-y-3 bg-white">
      {/* Copy entire prompt */}
      <div className="flex justify-end">
        <CopyButton text={allText} />
      </div>
      {all.map(([key, text]) => (
        <div key={key} className="border border-gray-100 rounded-lg overflow-hidden">
          <div className="flex items-center justify-between px-3 py-2 bg-gray-50">
            <span className="text-xs font-semibold text-gray-600">{toLabel(key)}</span>
            <CopyButton text={text} size="xs" />
          </div>
          <pre className="px-3 py-2 text-xs text-gray-600 whitespace-pre-wrap font-mono leading-relaxed bg-white">
            {text}
          </pre>
        </div>
      ))}
    </div>
  );
}

function BotKbContent({ value }: { value: unknown }) {
  return (
    <pre className="px-5 py-4 text-xs text-gray-600 bg-white overflow-x-auto font-mono leading-relaxed whitespace-pre-wrap break-words">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

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
      <pre className="px-5 py-4 pr-20 text-xs text-gray-600 overflow-x-auto max-w-full whitespace-pre-wrap break-words font-mono leading-relaxed">
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
        <pre className="text-xs text-gray-500 bg-gray-50 rounded-lg p-3 overflow-x-auto max-w-full whitespace-pre-wrap break-words">
          {JSON.stringify(rest, null, 2)}
        </pre>
      )}
    </div>
  );
}

function GenericContent({ value }: { value: unknown }) {
  return (
    <pre className="px-5 py-4 text-xs text-gray-600 bg-white overflow-x-auto max-w-full whitespace-pre-wrap break-words">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

// Dispatch a plan key to its purpose-built renderer (shared by Recent + History).
function sectionBody(sectionKey: string, value: unknown) {
  switch (sectionKey) {
    case "system_prompt_sections":
      return <SystemPromptSectionsContent value={value} />;
    case "bot_kb":
      return <BotKbContent value={value} />;
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

  return (
    <div
      className={`border border-gray-100 rounded-xl overflow-hidden min-w-0 ${
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
      {open && sectionBody(sectionKey, value)}
    </div>
  );
}

// ── History row (collapsible: renders full plan for v1, the delta for patches) ──

function HistoryRow({
  entry,
  plan,
}: {
  entry: HistoryEntry;
  plan: Record<string, unknown> | null;
}) {
  const [open, setOpen] = useState(false);

  // For the initial plan, render every populated section of the full plan.
  // For a patch, render only the keys it changed.
  const keys = entry.initial
    ? Object.keys(SECTION_TITLES).filter((k) => plan?.[k] != null)
    : Object.keys(entry.patch ?? {});

  const valueFor = (k: string): unknown =>
    entry.initial ? plan?.[k] : entry.patch?.[k];

  return (
    <div className="border border-gray-100 rounded-xl overflow-hidden min-w-0">
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between gap-3 px-4 py-3 bg-gray-50 hover:bg-gray-100 transition-colors text-left"
      >
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold text-gray-700">{vLabel(entry.version)}</span>
            {entry.initial ? (
              <span className="text-[10px] font-medium px-1.5 py-0.5 bg-blue-50 text-blue-600 rounded-full">
                initial plan
              </span>
            ) : (
              <span className="text-[10px] font-medium px-1.5 py-0.5 bg-amber-50 text-amber-700 rounded-full">
                patch
              </span>
            )}
            {entry.date && (
              <span className="text-xs text-gray-400">{entry.date.slice(0, 10)}</span>
            )}
          </div>
          <p className="text-sm text-gray-700 truncate mt-0.5">{entry.request}</p>
        </div>
        {open ? (
          <RiArrowUpSLine className="w-4 h-4 text-gray-400 shrink-0" />
        ) : (
          <RiArrowDownSLine className="w-4 h-4 text-gray-400 shrink-0" />
        )}
      </button>

      {open && (
        <div className="bg-white min-w-0 max-w-full overflow-x-hidden">
          {entry.reasoning && (
            <p className="px-4 pt-3 text-xs text-gray-500 italic">{entry.reasoning}</p>
          )}
          {keys.length === 0 && (
            <p className="px-4 py-4 text-sm text-gray-400">Nothing to display.</p>
          )}
          {keys.map((k) => (
            <div key={k} className="px-1 pb-2 min-w-0 overflow-x-hidden">
              <p className="px-4 pt-3 pb-1 text-xs font-semibold text-gray-500 uppercase tracking-wide">
                {SECTION_TITLES[k] ?? k}
              </p>
              {sectionBody(k, valueFor(k))}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Main component ──────────────────────────────────────────────────────────────

export default function PlanArtifact({ plan, planId, version, diff }: PlanArtifactProps) {
  const [tab, setTab] = useState<"recent" | "history">("recent");
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
          patch: pt.patch ?? {},
        }));
        // Synthesize the v1 entry — initial generation never writes a patch row
        entries.push({
          version: 1,
          request: "Initial plan generated",
          reasoning: "",
          date: planRow?.created_at ?? "",
          initial: true,
          patch: null,
        });
        entries.sort((a, b) => b.version - a.version);
        setHistory(entries);
      })
      .catch(() => setHistory([]))
      .finally(() => setHistoryLoading(false));
  }, [planId, tab]);

  const SECTIONS: { key: string; title: string }[] = [
    { key: "system_prompt_sections", title: "System Prompt" },
    { key: "workflow_blueprint", title: "Workflow Blueprint" },
    { key: "bot_kb", title: "Bot Knowledge Base" },
    { key: "build_notes", title: "Build Notes" },
    // legacy fallbacks shown only if present
    { key: "qualification_questions", title: "Qualification Questions" },
    { key: "objection_handling", title: "Objection Handling" },
    { key: "escalation_rules", title: "Escalation Rules" },
    { key: "kb_scaffold", title: "KB Scaffold" },
  ];

  return (
    <Card className="flex flex-col p-0 overflow-hidden min-h-150 max-w-full">
      {/* Header */}
      <div className="px-5 pt-4 pb-2 flex items-center justify-between border-b border-gray-100">
        <div>
          <p className="text-base font-semibold text-gray-800">
            {version != null ? `Plan ${vLabel(version)}` : "No plan yet"}
          </p>
          {planId && <p className="text-xs text-gray-400 mt-0.5 font-mono">{planId}</p>}
        </div>
        {/* Segmented toggle */}
        <div className="flex bg-gray-100 rounded-lg p-0.5 gap-0.5">
          {(["recent", "history"] as const).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`px-3 py-1 text-xs font-medium rounded-md transition-colors ${
                tab === t
                  ? "bg-white text-gray-800 shadow-sm"
                  : "text-gray-500 hover:text-gray-700"
              }`}
            >
              {t === "recent" ? "Recent" : "History"}
            </button>
          ))}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto overflow-x-hidden">
        {tab === "recent" && (
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
          <div className="p-5 min-w-0 overflow-x-hidden">
            {!planId && (
              <p className="text-sm text-gray-400 text-center pt-12">No plan loaded yet</p>
            )}
            {planId && historyLoading && (
              <p className="text-sm text-gray-400 text-center pt-12">Loading history…</p>
            )}
            {planId && !historyLoading && history.length === 0 && (
              <p className="text-sm text-gray-400 text-center pt-12">No history yet</p>
            )}
            {planId && !historyLoading && history.length > 0 && (
              <div className="space-y-2 min-w-0">
                {history.map((h) => (
                  <HistoryRow key={h.version} entry={h} plan={plan} />
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </Card>
  );
}
