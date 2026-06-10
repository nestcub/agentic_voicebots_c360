"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Card, CardHeader } from "@/components/Card";
import { RiArrowDownSLine, RiArrowUpSLine } from "react-icons/ri";

type PlanRow = { id: string; version: number; created_at: string; updated_at: string };
type PlanDetail = PlanRow & { plan: Record<string, unknown> };
type Patch = { id: string; version: number; admin_request: string; llm_reasoning: string; created_at: string };

function Section({ title, value }: { title: string; value: unknown }) {
  const [open, setOpen] = useState(false);
  if (value == null || (Array.isArray(value) && value.length === 0)) return null;
  return (
    <div className="border border-gray-100 rounded-xl overflow-hidden">
      <button onClick={() => setOpen((o) => !o)} className="w-full flex items-center justify-between px-5 py-3 text-sm font-semibold text-gray-700 bg-gray-50 hover:bg-gray-100 transition-colors">
        {title}
        {open ? <RiArrowUpSLine className="w-4 h-4 text-gray-400" /> : <RiArrowDownSLine className="w-4 h-4 text-gray-400" />}
      </button>
      {open && (
        <pre className="px-5 py-4 text-xs text-gray-600 bg-white overflow-x-auto whitespace-pre-wrap break-all">
          {JSON.stringify(value, null, 2)}
        </pre>
      )}
    </div>
  );
}

export default function PlansPage() {
  const params = useSearchParams();
  const [clientId, setClientId] = useState("");
  const [plans, setPlans] = useState<PlanRow[]>([]);
  const [selected, setSelected] = useState<PlanDetail | null>(null);
  const [patches, setPatches] = useState<Patch[]>([]);

  useEffect(() => {
    const id = localStorage.getItem("intel_client_id") ?? "";
    setClientId(id);
    if (id) fetch(`/api/intelligence/plans?client_id=${encodeURIComponent(id)}`).then((r) => r.json()).then((d) => setPlans(Array.isArray(d) ? d : [])).catch(() => {});
  }, []);

  useEffect(() => {
    const pid = params.get("id");
    if (pid) selectPlan(pid);
  }, [params]);

  async function selectPlan(id: string) {
    const [pRes, ptRes] = await Promise.all([
      fetch(`/api/intelligence/plans/${id}`).then((r) => r.json()),
      fetch(`/api/intelligence/plans/${id}/patches`).then((r) => r.json()),
    ]);
    setSelected(pRes);
    setPatches(Array.isArray(ptRes) ? ptRes : []);
  }

  const SECTIONS = selected ? [
    { title: "Workflow Blueprint",      value: selected.plan?.workflow_blueprint },
    { title: "System Prompt",           value: selected.plan?.system_prompt },
    { title: "Qualification Questions", value: selected.plan?.qualification_questions },
    { title: "Objection Handling",      value: selected.plan?.objection_handling },
    { title: "Escalation Rules",        value: selected.plan?.escalation_rules },
    { title: "KB Scaffold",             value: selected.plan?.kb_scaffold },
    { title: "Build Notes",             value: selected.plan?.build_notes },
  ] : [];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-lg font-semibold text-gray-800">Plans</h1>
        <p className="text-xs text-gray-400 mt-0.5">Browse workflow plan versions and patch history</p>
      </div>

      <div className="grid md:grid-cols-3 gap-6">
        {/* Plan list */}
        <Card className="p-0 overflow-hidden md:col-span-1">
          <CardHeader title="All Plans" hint={clientId || "no client"} />
          <div className="divide-y divide-gray-100">
            {plans.length === 0 && <p className="px-5 py-6 text-sm text-gray-400">No plans yet.</p>}
            {plans.map((p) => (
              <button key={p.id} onClick={() => selectPlan(p.id)} className={`w-full text-left px-5 py-3 hover:bg-gray-50 transition-colors ${selected?.id === p.id ? "bg-blue-50" : ""}`}>
                <p className="text-sm font-medium text-gray-800">v{p.version}</p>
                <p className="text-xs text-gray-400">{p.updated_at?.slice(0, 10) ?? p.created_at?.slice(0, 10)}</p>
              </button>
            ))}
          </div>
        </Card>

        {/* Plan detail */}
        <div className="md:col-span-2 space-y-4">
          {!selected && <Card className="p-8 text-center"><p className="text-sm text-gray-400">Select a plan to view its sections.</p></Card>}
          {selected && (
            <>
              <div className="flex items-center justify-between">
                <p className="text-sm font-semibold text-gray-700">Plan v{selected.version}</p>
                <p className="text-xs text-gray-400">Updated {selected.updated_at?.slice(0, 10)}</p>
              </div>
              <div className="space-y-2">
                {SECTIONS.map(({ title, value }) => <Section key={title} title={title} value={value} />)}
              </div>

              {/* Patches */}
              {patches.length > 0 && (
                <Card className="p-5 space-y-3">
                  <CardHeader title="Patch History" hint={`${patches.length} patches`} />
                  <div className="space-y-3">
                    {patches.map((pt) => (
                      <div key={pt.id} className="border-l-2 border-blue-200 pl-4">
                        <p className="text-xs text-gray-400">v{pt.version} · {pt.created_at?.slice(0, 10)}</p>
                        <p className="text-sm text-gray-700 font-medium mt-0.5">{pt.admin_request}</p>
                        {pt.llm_reasoning && <p className="text-xs text-gray-400 mt-0.5">{pt.llm_reasoning}</p>}
                      </div>
                    ))}
                  </div>
                </Card>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
