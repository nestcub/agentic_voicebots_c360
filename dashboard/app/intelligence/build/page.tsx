"use client";

import { useEffect, useState } from "react";
import { Card } from "@/components/Card";
import { RiCheckLine, RiFileCopyLine } from "react-icons/ri";
import { useIntelligence, usePlanCache } from "@/context/IntelligenceContext";

// Helper: snake_case → Title Case
const toLabel = (key: string) =>
  key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

// Canonical section ordering
const SECTION_ORDER = [
  "critical_rules",
  "roles",
  "objectives",
  "personality",
  "important_flow_rules",
  "guardrails",
  "instructions",
  "conversational_flow",
  "closure",
  "objection_handling",
  "conversation_example",
  "safety_guardrails",
];

// ── Per-section card with patch box ──────────────────────────────────────────

interface SectionCardProps {
  sectionKey: string;
  text: string;
  planId: string | null;
  onPatchSuccess: (sections: Record<string, string>) => void;
}

function SectionCard({ sectionKey, text, planId, onPatchSuccess }: SectionCardProps) {
  const [copied, setCopied] = useState(false);
  const [patchOpen, setPatchOpen] = useState(false);
  const [patchRequest, setPatchRequest] = useState("");
  const [patchLoading, setPatchLoading] = useState(false);
  const [patchError, setPatchError] = useState<string | null>(null);

  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard unavailable */
    }
  }

  async function applyPatch() {
    if (!planId || !patchRequest.trim()) return;
    setPatchLoading(true);
    setPatchError(null);
    try {
      const res = await fetch("/api/intelligence/patch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          plan_id: planId,
          request: patchRequest.trim(),
          section: sectionKey,
        }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      // data.patch may contain system_prompt_sections with changed keys
      const patch = data.patch as Record<string, unknown>;
      if (patch?.system_prompt_sections) {
        onPatchSuccess(patch.system_prompt_sections as Record<string, string>);
      }
      setPatchRequest("");
      setPatchOpen(false);
    } catch (err) {
      setPatchError(err instanceof Error ? err.message : "Patch failed");
    } finally {
      setPatchLoading(false);
    }
  }

  return (
    <div className="border border-gray-100 rounded-xl overflow-hidden">
      {/* Section header */}
      <div className="flex items-center justify-between gap-2 px-4 py-2.5 bg-gray-50 border-b border-gray-100">
        <span className="text-sm font-semibold text-gray-700">{toLabel(sectionKey)}</span>
        <div className="flex items-center gap-2 shrink-0">
          <button
            onClick={copy}
            className="flex items-center gap-1 px-2 py-1 text-xs font-medium rounded-md bg-white border border-gray-200 text-gray-500 hover:bg-gray-100 transition-colors"
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
          <button
            onClick={() => { setPatchOpen((o) => !o); setPatchError(null); }}
            className="flex items-center gap-1 px-2 py-1 text-xs font-medium rounded-md bg-blue-50 border border-blue-100 text-blue-600 hover:bg-blue-100 transition-colors"
          >
            Patch this section
          </button>
        </div>
      </div>

      {/* Section body */}
      <pre className="px-4 py-3 text-xs text-gray-600 overflow-x-auto whitespace-pre-wrap wrap-break-word font-mono leading-relaxed bg-white">
        {text}
      </pre>

      {/* Inline patch box */}
      {patchOpen && (
        <div className="px-4 pb-4 pt-2 bg-gray-50 border-t border-gray-100 space-y-2">
          <textarea
            className="w-full rounded-lg bg-white border border-gray-200 text-sm text-gray-800 placeholder-gray-400 p-2 resize-none focus:outline-none focus:border-blue-300"
            rows={2}
            placeholder="Describe the change for this section…"
            value={patchRequest}
            onChange={(e) => setPatchRequest(e.target.value)}
          />
          {patchError && <p className="text-xs text-red-500">{patchError}</p>}
          <div className="flex items-center gap-2">
            <button
              onClick={applyPatch}
              disabled={patchLoading || !patchRequest.trim()}
              className="px-3 py-1 text-xs font-medium rounded bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50 transition-colors"
            >
              {patchLoading ? "Applying…" : "Apply Patch"}
            </button>
            <button
              onClick={() => { setPatchOpen(false); setPatchError(null); }}
              className="px-3 py-1 text-xs font-medium rounded bg-white border border-gray-200 text-gray-600 hover:bg-gray-100 transition-colors"
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// ── System-prompt sections panel ─────────────────────────────────────────────

interface SystemPromptSectionsPanelProps {
  sections: Record<string, string | undefined>;
  planId: string | null;
  onPatchSuccess: (sections: Record<string, string>) => void;
}

function SystemPromptSectionsPanel({
  sections,
  planId,
  onPatchSuccess,
}: SystemPromptSectionsPanelProps) {
  const entries = SECTION_ORDER
    .filter(k => sections[k] != null && String(sections[k]).trim() !== "")
    .map(k => [k, sections[k] as string] as [string, string]);
  // append any keys not in SECTION_ORDER (future-proofing)
  const knownKeys = new Set(SECTION_ORDER);
  const extra = Object.entries(sections).filter(
    ([k, v]) => !knownKeys.has(k) && v != null && String(v).trim() !== ""
  ) as [string, string][];
  const allEntries = [...entries, ...extra];

  if (allEntries.length === 0) return null;

  return (
    <div className="space-y-2">
      {allEntries.map(([key, text]) => (
        <SectionCard
          key={key}
          sectionKey={key}
          text={text}
          planId={planId}
          onPatchSuccess={onPatchSuccess}
        />
      ))}
    </div>
  );
}

// ── Bot KB panel ──────────────────────────────────────────────────────────────

function BotKBPanel({ kb }: { kb: unknown }) {
  const [copied, setCopied] = useState(false);
  const text = JSON.stringify(kb, null, 2);

  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard unavailable */
    }
  }

  return (
    <Card className="p-0 overflow-hidden">
      <div className="flex items-center justify-between px-5 pt-4 pb-2 border-b border-gray-100">
        <p className="text-base font-semibold text-gray-800">Bot Knowledge Base</p>
        <button
          onClick={copy}
          className="flex items-center gap-1 px-2 py-1 text-xs font-medium rounded-md bg-gray-100 text-gray-500 hover:bg-gray-200 hover:text-gray-700 transition-colors"
        >
          {copied ? (
            <>
              <RiCheckLine className="w-3.5 h-3.5 text-emerald-500" /> Copied
            </>
          ) : (
            <>
              <RiFileCopyLine className="w-3.5 h-3.5" /> Copy KB
            </>
          )}
        </button>
      </div>
      <pre className="px-5 py-4 text-xs text-gray-600 overflow-x-auto font-mono leading-relaxed whitespace-pre-wrap wrap-break-word bg-white">
        {text}
      </pre>
    </Card>
  );
}

// ── Workflow Blueprint panel ───────────────────────────────────────────────────

type Stage = {
  stage_id: number;
  name: string;
  node_type: string;
  purpose: string;
};

type WorkflowBlueprint = {
  description?: string;
  stages?: Stage[];
};

function WorkflowBlueprintPanel({ blueprint }: { blueprint: WorkflowBlueprint }) {
  return (
    <Card className="p-0 overflow-hidden">
      <div className="px-5 pt-4 pb-2 border-b border-gray-100">
        <p className="text-base font-semibold text-gray-800">Workflow Blueprint</p>
        {blueprint.description && (
          <p className="text-xs text-gray-400 mt-0.5">{blueprint.description}</p>
        )}
      </div>
      <div className="p-5 space-y-2">
        {(blueprint.stages ?? []).map((stage) => (
          <div key={stage.stage_id} className="p-3 border border-gray-100 rounded-lg">
            <div className="flex items-center gap-2">
              <span className="text-xs font-mono bg-gray-100 text-gray-500 px-1.5 py-0.5 rounded">
                {stage.node_type}
              </span>
              <span className="text-sm font-medium text-gray-800">{stage.name}</span>
            </div>
            {stage.purpose && (
              <p className="text-xs text-gray-500 mt-1">{stage.purpose}</p>
            )}
          </div>
        ))}
      </div>
    </Card>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function BuildPage() {
  const { clientId } = useIntelligence();
  const { latestPlan, plansLoading } = usePlanCache();

  const [plan, setPlan] = useState<Record<string, unknown> | null>(null);
  const [planId, setPlanId] = useState<string | null>(null);

  // Chat bar state
  const [chatModel, setChatModel] = useState("gpt-5.4");
  const [chatMessage, setChatMessage] = useState("");
  const [chatLoading, setChatLoading] = useState(false);
  const [chatReply, setChatReply] = useState<string | null>(null);
  const [chatError, setChatError] = useState<string | null>(null);

  // Hydrate plan from context
  useEffect(() => {
    if (latestPlan && !plan) {
      setPlan(latestPlan.plan ?? null);
      setPlanId(latestPlan.id);
    }
  }, [latestPlan]);

  // Merge patched system_prompt_sections back into plan state
  function handleSectionPatchSuccess(changedSections: Record<string, string>) {
    setPlan((prev) => {
      if (!prev) return prev;
      const existingSections =
        (prev.system_prompt_sections as Record<string, string | undefined> | undefined) ?? {};
      return {
        ...prev,
        system_prompt_sections: { ...existingSections, ...changedSections },
      };
    });
  }

  async function sendChat() {
    if (!clientId || !chatMessage.trim()) return;
    setChatLoading(true);
    setChatError(null);
    setChatReply(null);
    try {
      const res = await fetch("/api/intelligence/converse", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          client_id: clientId,
          message: chatMessage.trim(),
          model: chatModel,
          intent_aware: true,
        }),
      });
      if (!res.ok) throw new Error(`Server error ${res.status}`);
      const data = await res.json();
      setChatReply(data.reply ?? "Done.");
      setChatMessage("");
      if (data.plan_changed && data.plan?.system_prompt_sections) {
        handleSectionPatchSuccess(data.plan.system_prompt_sections as Record<string, string>);
      }
      if (data.plan_id) setPlanId(data.plan_id);
    } catch (err) {
      setChatError(err instanceof Error ? err.message : "Request failed.");
    } finally {
      setChatLoading(false);
    }
  }

  // Derive plan fields
  const systemPromptSections = plan?.system_prompt_sections as
    | Record<string, string | undefined>
    | undefined;
  const hasSections =
    systemPromptSections != null && Object.keys(systemPromptSections).length > 0;
  const workflowBlueprint = plan?.workflow_blueprint as WorkflowBlueprint | undefined;
  const botKb = plan?.bot_kb;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-lg font-semibold text-gray-800">Build</h1>
        <p className="text-xs text-gray-400 mt-0.5">Generated bot plan</p>
      </div>

      {!clientId && (
        <div className="p-4 bg-amber-50 border border-amber-200 rounded-xl text-sm text-amber-700">
          No Client ID set.{" "}
          <a href="/intelligence" className="underline font-medium">Go to Bots.</a>
        </div>
      )}

      {plansLoading && !plan && (
        <p className="text-sm text-gray-400">Loading plan…</p>
      )}

      {plan && !hasSections && !workflowBlueprint && !botKb && (
        <p className="text-sm text-gray-400">No plan generated yet.</p>
      )}

      {/* System Prompt Sections */}
      {plan && hasSections && (
        <Card className="p-0 overflow-hidden">
          <div className="px-5 pt-4 pb-2 border-b border-gray-100">
            <p className="text-base font-semibold text-gray-800">System Prompt</p>
            <p className="text-xs text-gray-400 mt-0.5">12-section view — patch individual sections below</p>
          </div>
          <div className="p-5 space-y-2">
            <SystemPromptSectionsPanel
              sections={systemPromptSections!}
              planId={planId}
              onPatchSuccess={handleSectionPatchSuccess}
            />
          </div>
        </Card>
      )}

      {/* Workflow Blueprint */}
      {plan && workflowBlueprint && (
        <WorkflowBlueprintPanel blueprint={workflowBlueprint} />
      )}

      {/* Bot KB */}
      {plan && botKb != null && <BotKBPanel kb={botKb} />}

      {/* Chat / Converse bar */}
      <Card className="p-0 overflow-hidden">
        <div className="px-5 pt-4 pb-2 border-b border-gray-100 flex items-center justify-between">
          <p className="text-base font-semibold text-gray-800">Ask / Patch</p>
          <select
            value={chatModel}
            onChange={e => setChatModel(e.target.value)}
            className="text-xs border border-gray-200 rounded-lg px-2 py-1 text-gray-600 focus:outline-none focus:ring-1 focus:ring-blue-400"
          >
            <option value="sonnet">Sonnet (Anthropic)</option>
            <option value="gpt-4.1">GPT-4.1</option>
            <option value="gpt-5.4">GPT-5.4 (Recommended)</option>
          </select>
        </div>
        <div className="p-5 space-y-3">
          {chatReply && (
            <div className="p-3 bg-gray-50 border border-gray-100 rounded-lg text-sm text-gray-700 whitespace-pre-wrap">
              {chatReply}
            </div>
          )}
          {chatError && (
            <p className="text-xs text-red-500">{chatError}</p>
          )}
          <textarea
            className="w-full rounded-lg border border-gray-200 text-sm text-gray-800 placeholder-gray-400 p-3 resize-y focus:outline-none focus:ring-2 focus:ring-blue-400"
            rows={5}
            placeholder="Paste a call transcript, describe bot failures, or ask any question. The AI will patch the right sections."
            value={chatMessage}
            onChange={e => setChatMessage(e.target.value)}
            disabled={chatLoading}
          />
          <div className="flex items-center gap-3">
            <button
              onClick={sendChat}
              disabled={chatLoading || !chatMessage.trim() || !clientId}
              className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-40 transition-colors flex items-center gap-2"
            >
              {chatLoading && (
                <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z"/>
                </svg>
              )}
              {chatLoading ? "Thinking…" : "Send"}
            </button>
            {chatLoading && (
              <span className="text-xs text-gray-400">This can take up to 60s…</span>
            )}
          </div>
        </div>
      </Card>
    </div>
  );
}
