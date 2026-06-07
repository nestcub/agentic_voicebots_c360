"use client";

import { useScoped } from "@/lib/useScoped";
import { Card, CardHeader } from "@/components/Card";
import { StatusBadge } from "@/components/StatusBadge";
import type { Lead } from "@/lib/types";

export default function LeadsPage() {
  const { data: leads, loading } = useScoped<Lead[]>((ds, s) => ds.getLeads(s), []);

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-slate-900">Leads</h1>
      <Card className="p-0 overflow-hidden">
        <CardHeader title="Lead inventory" hint={loading ? "Loading…" : `${leads.length} leads in scope`} />
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs uppercase tracking-wide text-slate-500 border-y border-slate-100">
                <th className="px-5 py-2.5 font-medium">Name</th>
                <th className="px-5 py-2.5 font-medium">Vehicle</th>
                <th className="px-5 py-2.5 font-medium">Region / Branch</th>
                <th className="px-5 py-2.5 font-medium">Source</th>
                <th className="px-5 py-2.5 font-medium">Score</th>
                <th className="px-5 py-2.5 font-medium">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {leads.map((l) => (
                <tr key={l.id} className="hover:bg-slate-50">
                  <td className="px-5 py-2.5">
                    <p className="font-medium text-slate-800">{l.name}</p>
                    <p className="text-xs text-slate-400">{l.phone}</p>
                  </td>
                  <td className="px-5 py-2.5 text-slate-700">{l.vehicle_model}</td>
                  <td className="px-5 py-2.5 text-slate-700">{l.region} · {l.branch}</td>
                  <td className="px-5 py-2.5 text-slate-600">{l.source}</td>
                  <td className="px-5 py-2.5 text-slate-600">{l.lead_score ?? "—"}</td>
                  <td className="px-5 py-2.5"><StatusBadge status={l.status} /></td>
                </tr>
              ))}
              {leads.length === 0 && !loading && (
                <tr><td colSpan={6} className="px-5 py-8 text-center text-slate-400">No leads in scope.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
