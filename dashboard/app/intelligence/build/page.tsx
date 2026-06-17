"use client";

import { useEffect, useState } from "react";
import ChatThread from "@/components/intelligence/ChatThread";
import PlanArtifact from "@/components/intelligence/PlanArtifact";
import { Card } from "@/components/Card";
import { RiBookOpenLine, RiCloseLine, RiCheckLine, RiFileCopyLine } from "react-icons/ri";
import { useIntelligence, usePlanCache, useKnowledgeCache } from "@/context/IntelligenceContext";

// Helper: snake_case → Title Case
const toLabel = (key: string) =>
  key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

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
  const entries = Object.entries(sections).filter(
    ([, v]) => v != null && String(v).trim() !== ""
  ) as [string, string][];

  if (entries.length === 0) return null;

  return (
    <div className="space-y-2">
      {entries.map(([key, text]) => (
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

// ── Main page ─────────────────────────────────────────────────────────────────

export default function BuildPage() {
  const { clientId } = useIntelligence();
  const { latestPlan, plansLoading } = usePlanCache();
  const { knowledgeFacts, knowledgeLoading, refreshKnowledge } = useKnowledgeCache();

  const [plan, setPlan] = useState<Record<string, unknown> | null>(null);
  const [planId, setPlanId] = useState<string | null>(null);
  const [version, setVersion] = useState<number | null>(null);
  const [diff, setDiff] = useState<Record<string, { before: unknown; after: unknown }> | null>(null);
  const [knowledgeOpen, setKnowledgeOpen] = useState(false);

  const [useCase, setUseCase] = useState("");
  const [useCaseSaved, setUseCaseSaved] = useState(false);
  const [kbContent, setKbContent] = useState("");
  const [kbSaved, setKbSaved] = useState(false);
  const [kbOpen, setKbOpen] = useState(false);

  // Hydrate plan from context
  useEffect(() => {
    if (latestPlan && !plan) {
      setPlan(latestPlan.plan ?? null);
      setPlanId(latestPlan.id);
      setVersion(latestPlan.version);
    }
  }, [latestPlan]);

  // Prefill use case and KB when clientId changes
  useEffect(() => {
    if (!clientId) return;
    fetch(`/api/intelligence/session/${clientId}`)
      .then((r) => r.json())
      .then((d) => setUseCase(d.use_case || ""))
      .catch(() => {});
    fetch(`/api/intelligence/kb/${clientId}`)
      .then((r) => r.json())
      .then((d) => setKbContent(d.content || ""))
      .catch(() => {});
  }, [clientId]);

  function handlePlanUpdate(data: {
    plan: Record<string, unknown> | null;
    plan_id: string | null;
    diff: Record<string, { before: unknown; after: unknown }> | null;
    version: number | null;
    plan_changed: boolean;
    mode: string;
  }) {
    if (data.plan) setPlan(data.plan);
    if (data.plan_id) setPlanId(data.plan_id);
    if (data.version != null) setVersion(data.version);
    if (data.plan_changed && data.diff) setDiff(data.diff);
    else setDiff(null);
  }

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

  async function saveUseCase() {
    await fetch(`/api/intelligence/session/${clientId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ use_case: useCase }),
    });
    setUseCaseSaved(true);
    setTimeout(() => setUseCaseSaved(false), 2000);
  }

  async function saveKb() {
    await fetch(`/api/intelligence/kb/${clientId}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content: kbContent }),
    });
    setKbSaved(true);
    setTimeout(() => setKbSaved(false), 2000);
  }

  async function approveFact(id: string) {
    try {
      await fetch(`/api/intelligence/knowledge/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: "active" }),
      });
      refreshKnowledge();
    } catch {
      // ignore
    }
  }

  const activeFacts = knowledgeFacts.filter((f) => f.status === "active");
  const pendingFacts = knowledgeFacts.filter((f) => f.status === "pending");

  // Derive plan fields for new shape
  const systemPromptSections = plan?.system_prompt_sections as
    | Record<string, string | undefined>
    | undefined;
  const hasSections =
    systemPromptSections != null && Object.keys(systemPromptSections).length > 0;
  const botKb = plan?.bot_kb;

  return (
    <div className="space-y-6">
      {/* Page header */}
      <div>
        <h1 className="text-lg font-semibold text-gray-800">Build</h1>
        <p className="text-xs text-gray-400 mt-0.5">Conversational workflow designer</p>
      </div>

      {!clientId && (
        <div className="p-4 bg-amber-50 border border-amber-200 rounded-xl text-sm text-amber-700">
          No Client ID set.{" "}
          <a href="/intelligence" className="underline font-medium">
            Set one on the hub.
          </a>
        </div>
      )}

      {plansLoading && !plan && (
        <p className="text-sm text-gray-400">Loading plan…</p>
      )}

      {/* Main split layout */}
      <div className="grid lg:grid-cols-[1fr_1.2fr] gap-6">
        {/* Left: Use Case + KB + Chat */}
        <div className="min-w-0 flex flex-col gap-0 rounded-xl overflow-hidden border border-white/10 bg-white/5">
          {/* Use Case section */}
          <div className="flex flex-col gap-2 p-4 border-b border-white/10">
            <label className="text-xs font-semibold text-white/50 uppercase tracking-wide">Use Case</label>
            <textarea
              className="w-full rounded-lg bg-white/5 border border-white/10 text-sm text-black placeholder-gray-400 p-2 resize-none focus:outline-none focus:border-white/30"
              rows={3}
              placeholder="Describe the bot you want to build..."
              value={useCase}
              onChange={(e) => { setUseCase(e.target.value); setUseCaseSaved(false); }}
            />
            <button
              onClick={saveUseCase}
              className="self-end text-xs px-3 py-1 rounded bg-white/10 hover:bg-white/20 text-white transition"
            >
              {useCaseSaved ? "Saved ✓" : "Save"}
            </button>
          </div>

          {/* Knowledge Base section (collapsible) */}
          <div className="border-b border-white/10">
            <button
              onClick={() => setKbOpen((o) => !o)}
              className="w-full flex items-center justify-between px-4 py-2 text-xs font-semibold text-white/50 uppercase tracking-wide hover:text-white/70 transition"
            >
              <span>Bot&apos;s Knowledge Base</span>
              <span>{kbOpen ? "▲" : "▼"}</span>
            </button>
            {kbOpen && (
              <div className="flex flex-col gap-2 px-4 pb-4">
                <textarea
                  className="w-full rounded-lg bg-white/5 border border-white/10 text-sm text-black placeholder-gray-400 p-2 resize-none focus:outline-none focus:border-white/30"
                  rows={6}
                  placeholder="Paste FAQs, pricing, scripts, escalation contacts..."
                  value={kbContent}
                  onChange={(e) => { setKbContent(e.target.value); setKbSaved(false); }}
                />
                <button
                  onClick={saveKb}
                  className="self-end text-xs px-3 py-1 rounded bg-white/10 hover:bg-white/20 text-white transition"
                >
                  {kbSaved ? "Saved ✓" : "Save"}
                </button>
              </div>
            )}
          </div>

          {/* Chat */}
          <div className="flex-1">
            <ChatThread clientId={clientId} onPlanUpdate={handlePlanUpdate} />
          </div>
        </div>

        {/* Right: Plan artifact + Knowledge drawer toggle */}
        <div className="relative min-w-0 space-y-4">
          {/* Artifact column header with knowledge toggle */}
          <div className="flex items-center justify-between mb-3">
            <span className="text-sm font-medium text-gray-600">Plan Artifact</span>
            <button
              onClick={() => { setKnowledgeOpen((o) => !o); if (!knowledgeOpen) refreshKnowledge(); }}
              title="Toggle Knowledge Drawer"
              className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg border transition-colors ${
                knowledgeOpen
                  ? "bg-blue-50 border-blue-200 text-blue-700"
                  : "bg-white border-gray-200 text-gray-600 hover:bg-gray-50"
              }`}
            >
              <RiBookOpenLine className="w-4 h-4" />
              Knowledge
            </button>
          </div>

          {/* Knowledge side panel */}
          {knowledgeOpen && (
            <Card className="mb-4 p-0 overflow-hidden">
              <div className="flex items-center justify-between px-5 pt-4 pb-2 border-b border-gray-100">
                <p className="text-base font-semibold text-gray-800">Knowledge Base</p>
                <button
                  onClick={() => setKnowledgeOpen(false)}
                  className="p-1 text-gray-400 hover:text-gray-600 rounded transition-colors"
                >
                  <RiCloseLine className="w-4 h-4" />
                </button>
              </div>

              <div className="p-5 space-y-5 max-h-72 overflow-y-auto">
                {knowledgeLoading && (
                  <p className="text-sm text-gray-400 text-center">Loading…</p>
                )}

                {!knowledgeLoading && knowledgeFacts.length === 0 && (
                  <p className="text-sm text-gray-400 text-center">No knowledge facts yet.</p>
                )}

                {/* Pending facts */}
                {!knowledgeLoading && pendingFacts.length > 0 && (
                  <div>
                    <p className="text-xs font-semibold text-amber-600 uppercase tracking-wide mb-2">
                      Pending ({pendingFacts.length})
                    </p>
                    <div className="space-y-2">
                      {pendingFacts.map((f) => (
                        <div
                          key={f.id}
                          className="flex items-start gap-3 p-3 bg-amber-50 border border-amber-100 rounded-lg"
                        >
                          <div className="flex-1 min-w-0">
                            <p className="text-xs font-medium text-gray-700">{f.topic}</p>
                            <p className="text-xs text-gray-500 mt-0.5 truncate">{f.fact}</p>
                          </div>
                          <button
                            onClick={() => approveFact(f.id)}
                            className="shrink-0 flex items-center gap-1 px-2 py-1 text-xs font-medium bg-white border border-green-200 text-green-700 rounded hover:bg-green-50 transition-colors"
                          >
                            <RiCheckLine className="w-3 h-3" />
                            Approve
                          </button>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Active facts */}
                {!knowledgeLoading && activeFacts.length > 0 && (
                  <div>
                    <p className="text-xs font-semibold text-green-600 uppercase tracking-wide mb-2">
                      Active ({activeFacts.length})
                    </p>
                    <div className="space-y-2">
                      {activeFacts.map((f) => (
                        <div
                          key={f.id}
                          className="p-3 bg-gray-50 border border-gray-100 rounded-lg"
                        >
                          <p className="text-xs font-medium text-gray-700">{f.topic}</p>
                          <p className="text-xs text-gray-500 mt-0.5">{f.fact}</p>
                          {f.source && (
                            <p className="text-xs text-gray-400 mt-0.5 italic">
                              source: {f.source}
                            </p>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </Card>
          )}

          {/* System Prompt Sections (new plan shape) */}
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

          <PlanArtifact plan={plan} planId={planId} version={version} diff={diff} />

          {/* Bot KB panel (new plan shape) */}
          {plan && botKb != null && <BotKBPanel kb={botKb} />}
        </div>
      </div>
    </div>
  );
}
