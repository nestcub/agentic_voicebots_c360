"use client";

import { useEffect, useState } from "react";
import ChatThread from "@/components/intelligence/ChatThread";
import PlanArtifact from "@/components/intelligence/PlanArtifact";
import { useIntelligence, usePlanCache } from "@/context/IntelligenceContext";

// ── Main page ─────────────────────────────────────────────────────────────────

export default function BuildPage() {
  const { clientId } = useIntelligence();
  const { latestPlan } = usePlanCache();

  const [plan, setPlan] = useState<Record<string, unknown> | null>(null);
  const [planId, setPlanId] = useState<string | null>(null);
  const [version, setVersion] = useState<number | null>(null);
  const [diff, setDiff] = useState<Record<string, unknown> | null>(null);

  // Hydrate plan from context
  useEffect(() => {
    if (latestPlan && !plan) {
      setPlan(latestPlan.plan ?? null);
      setPlanId(latestPlan.id);
      setVersion(latestPlan.version ?? null);
    }
  }, [latestPlan]);

  function handlePlanUpdate(data: {
    plan: Record<string, unknown> | null;
    plan_id: string | null;
    diff: Record<string, unknown> | null;
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

  // suppress unused warning — handleSectionPatchSuccess is kept for future patch boxes
  void handleSectionPatchSuccess;

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-lg font-semibold text-gray-800">Build</h1>
        <p className="text-xs text-gray-400 mt-0.5">Conversational workflow designer</p>
      </div>

      {!clientId && (
        <div className="p-4 bg-amber-50 border border-amber-200 rounded-xl text-sm text-amber-700">
          No Client ID set.{" "}
          <a href="/intelligence" className="underline font-medium">Go to Bots.</a>
        </div>
      )}

      <div className="grid lg:grid-cols-[1fr_1.2fr] gap-6 items-start">
        {/* Left: Chat */}
        <ChatThread clientId={clientId} planId={planId} onPlanUpdate={handlePlanUpdate} />

        {/* Right: Versioned plan output */}
        <PlanArtifact plan={plan} planId={planId} version={version} diff={diff} />
      </div>
    </div>
  );
}
