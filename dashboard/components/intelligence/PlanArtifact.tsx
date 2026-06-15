"use client";

import { useEffect, useState } from "react";
import { Card } from "@/components/Card";
import { RiArrowDownSLine, RiArrowUpSLine } from "react-icons/ri";

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

type WorkflowStage = {
  stage_id: string;
  name: string;
  node_type: string;
  purpose: string;
  chat360_config: unknown;
};

function WorkflowBlueprintContent({
  value,
}: {
  value: unknown;
}) {
  const bp = value as {
    description?: string;
    stages?: WorkflowStage[];
  } | null;
  if (!bp) return null;
  return (
    <div className="px-5 py-4 space-y-3 bg-white">
      {bp.description && (
        <p className="text-sm text-gray-700">{bp.description}</p>
      )}
      {bp.stages && bp.stages.length > 0 && (
        <ol className="space-y-1">
          {bp.stages.map((s, i) => (
            <li key={s.stage_id ?? i} className="text-sm text-gray-700 flex items-start gap-1.5">
              <span className="text-blue-500 font-semibold shrink-0">{i + 1}.</span>
              <span>
                <span className="font-medium">{s.name}</span>
                {s.purpose && (
                  <span className="text-gray-500"> — {s.purpose}</span>
                )}
              </span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

function SystemPromptContent({ value }: { value: unknown }) {
  return (
    <pre className="px-5 py-4 text-xs text-gray-600 bg-white overflow-x-auto whitespace-pre-wrap break-all font-mono">
      {typeof value === "string" ? value : JSON.stringify(value, null, 2)}
    </pre>
  );
}

function GenericContent({ value }: { value: unknown }) {
  return (
    <pre className="px-5 py-4 text-xs text-gray-600 bg-white overflow-x-auto whitespace-pre-wrap break-all">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

function DiffPanel({
  before,
  after,
}: {
  before: unknown;
  after: unknown;
}) {
  return (
    <div className="mx-5 mb-4 space-y-1">
      <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide">Changes</p>
      <div className="grid grid-cols-2 gap-2 text-xs">
        <div className="bg-red-50 border border-red-100 rounded p-2 text-red-700 font-mono whitespace-pre-wrap break-all">
          {JSON.stringify(before, null, 2)}
        </div>
        <div className="bg-emerald-50 border border-emerald-100 rounded p-2 text-emerald-700 font-mono whitespace-pre-wrap break-all">
          {JSON.stringify(after, null, 2)}
        </div>
      </div>
    </div>
  );
}

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
    if (sectionKey === "workflow_blueprint") {
      return <WorkflowBlueprintContent value={value} />;
    }
    if (sectionKey === "system_prompt") {
      return <SystemPromptContent value={value} />;
    }
    return <GenericContent value={value} />;
  };

  return (
    <div className={`border border-gray-100 rounded-xl overflow-hidden ${isFlashing ? "flash-row" : ""}`}>
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

export default function PlanArtifact({
  plan,
  planId,
  version,
  diff,
}: PlanArtifactProps) {
  const [tab, setTab] = useState<"current" | "history">("current");
  const [patches, setPatches] = useState<Patch[]>([]);
  const [patchLoading, setPatchLoading] = useState(false);
  const [flashedKeys, setFlashedKeys] = useState<Set<string>>(new Set());

  // Flash changed sections for 2s when diff changes
  useEffect(() => {
    if (!diff || Object.keys(diff).length === 0) return;
    const keys = new Set(Object.keys(diff));
    setFlashedKeys(keys);
    const timer = setTimeout(() => setFlashedKeys(new Set()), 2000);
    return () => clearTimeout(timer);
  }, [diff]);

  // Fetch patches when planId changes or history tab is selected
  useEffect(() => {
    if (!planId || tab !== "history") return;
    setPatchLoading(true);
    fetch(`/api/intelligence/plans/${planId}/patches`)
      .then((r) => r.json())
      .then((d) => setPatches(Array.isArray(d) ? d : []))
      .catch(() => setPatches([]))
      .finally(() => setPatchLoading(false));
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
          {planId && (
            <p className="text-xs text-gray-400 mt-0.5 font-mono">{planId}</p>
          )}
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
              <p className="text-sm text-gray-400 text-center pt-12">
                No plan loaded yet
              </p>
            )}
            {planId && patchLoading && (
              <p className="text-sm text-gray-400 text-center pt-12">
                Loading patches…
              </p>
            )}
            {planId && !patchLoading && patches.length === 0 && (
              <p className="text-sm text-gray-400 text-center pt-12">
                No patches recorded yet
              </p>
            )}
            {planId && !patchLoading && patches.length > 0 && (
              <div className="space-y-3">
                {patches.map((pt) => (
                  <div key={pt.id} className="border-l-2 border-blue-200 pl-4">
                    <p className="text-xs text-gray-400">
                      v{pt.version} · {pt.created_at?.slice(0, 10)}
                    </p>
                    <p className="text-sm text-gray-700 font-medium mt-0.5">
                      {pt.admin_request}
                    </p>
                    {pt.llm_reasoning && (
                      <p className="text-xs text-gray-400 mt-0.5">
                        {pt.llm_reasoning}
                      </p>
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
