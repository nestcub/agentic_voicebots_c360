"use client";

import { useEffect, useState } from "react";
import ChatThread from "@/components/intelligence/ChatThread";
import PlanArtifact from "@/components/intelligence/PlanArtifact";
import { Card } from "@/components/Card";
import { RiBookOpenLine, RiCloseLine, RiCheckLine } from "react-icons/ri";
import { useIntelligence, usePlanCache, useKnowledgeCache } from "@/context/IntelligenceContext";

export default function BuildPage() {
  const { clientId } = useIntelligence();
  const { latestPlan, plansLoading } = usePlanCache();
  const { knowledgeFacts, knowledgeLoading, refreshKnowledge } = useKnowledgeCache();

  const [plan, setPlan] = useState<Record<string, unknown> | null>(null);
  const [planId, setPlanId] = useState<string | null>(null);
  const [version, setVersion] = useState<number | null>(null);
  const [diff, setDiff] = useState<Record<string, { before: unknown; after: unknown }> | null>(null);
  const [knowledgeOpen, setKnowledgeOpen] = useState(false);

  // Hydrate plan from context
  useEffect(() => {
    if (latestPlan && !plan) {
      setPlan(latestPlan.plan ?? null);
      setPlanId(latestPlan.id);
      setVersion(latestPlan.version);
    }
  }, [latestPlan]);

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
        {/* Left: Chat */}
        <div>
          <ChatThread clientId={clientId} onPlanUpdate={handlePlanUpdate} />
        </div>

        {/* Right: Plan artifact + Knowledge drawer toggle */}
        <div className="relative">
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

          <PlanArtifact plan={plan} planId={planId} version={version} diff={diff} />
        </div>
      </div>
    </div>
  );
}
