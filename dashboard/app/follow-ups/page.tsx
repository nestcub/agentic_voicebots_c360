"use client";

import { useScoped } from "@/lib/useScoped";
import { Card, CardHeader } from "@/components/Card";
import { CommitmentBadge } from "@/components/StatusBadge";
import { StatCard } from "@/components/StatCard";
import type { Commitment } from "@/lib/types";

function fmt(due: string) {
  const d = new Date(due);
  const diffH = Math.round((d.getTime() - Date.now()) / 3.6e6);
  if (diffH < 0) return `${Math.abs(diffH)}h overdue`;
  if (diffH === 0) return "due now";
  return `in ${diffH}h`;
}

export default function FollowUpsPage() {
  const { data: commitments, loading } = useScoped<Commitment[]>((ds, s) => ds.getCommitments(s), []);

  const now = Date.now();
  const pending = commitments.filter((c) => c.state === "pending");
  const overdue = pending.filter((c) => new Date(c.due_at).getTime() < now);
  const exhausted = commitments.filter((c) => c.state === "exhausted");

  // Overdue first, then by soonest due.
  const sorted = [...commitments].sort((a, b) => new Date(a.due_at).getTime() - new Date(b.due_at).getTime());

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-slate-900">Follow-ups</h1>
      <p className="text-sm text-slate-500 -mt-3">
        The Commitment Ledger — every promised follow-up is durable and never dropped, even across goal changes.
      </p>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard label="Active" value={pending.length} />
        <StatCard label="Overdue" value={overdue.length} sub={overdue.length ? "SLA breached" : "on time"} />
        <StatCard label="Exhausted" value={exhausted.length} sub="needs human" />
        <StatCard label="Total tracked" value={commitments.length} />
      </div>

      <Card className="p-0 overflow-hidden">
        <CardHeader title="Commitment ledger" hint={loading ? "Loading…" : `${commitments.length} commitments in scope`} />
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs uppercase tracking-wide text-slate-500 border-y border-slate-100">
                <th className="px-5 py-2.5 font-medium">Branch</th>
                <th className="px-5 py-2.5 font-medium">Goal</th>
                <th className="px-5 py-2.5 font-medium">Due</th>
                <th className="px-5 py-2.5 font-medium">Retries</th>
                <th className="px-5 py-2.5 font-medium">State</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {sorted.map((c) => {
                const isOverdue = c.state === "pending" && new Date(c.due_at).getTime() < now;
                return (
                  <tr key={c.id} className={isOverdue ? "bg-rose-50/60" : "hover:bg-slate-50"}>
                    <td className="px-5 py-2.5 text-slate-700">{c.branch || "—"}</td>
                    <td className="px-5 py-2.5 text-slate-600">
                      {(c.goal_context?.focus_detail as string) ?? "—"}
                    </td>
                    <td className={`px-5 py-2.5 ${isOverdue ? "text-rose-600 font-medium" : "text-slate-600"}`}>
                      {fmt(c.due_at)}
                    </td>
                    <td className="px-5 py-2.5 text-slate-600">{c.retries}/{c.max_retries}</td>
                    <td className="px-5 py-2.5"><CommitmentBadge state={c.state} /></td>
                  </tr>
                );
              })}
              {commitments.length === 0 && !loading && (
                <tr><td colSpan={5} className="px-5 py-8 text-center text-slate-400">No commitments in scope.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
