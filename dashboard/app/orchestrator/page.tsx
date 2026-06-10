"use client";

import { useEffect, useState } from "react";
import { Card } from "@/components/Card";
import type { DispatchRecommendation } from "@/lib/types";
import {
  RiCheckboxCircleLine,
  RiCalendarEventLine,
  RiCloseLine,
  RiTimeLine,
  RiPhoneLine,
  RiUserLine,
} from "react-icons/ri";

// ── Helpers ──────────────────────────────────────────────────────────────────

function formatCallTime(mins: number): string {
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

function formatDateTime(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

// ── Status badges ─────────────────────────────────────────────────────────────

function ActiveStatusBadge({ status }: { status: "pending_approval" | "scheduled" }) {
  if (status === "pending_approval") {
    return (
      <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-amber-100 text-amber-700">
        Awaiting Approval
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-blue-100 text-blue-700">
      Scheduled
    </span>
  );
}

function PastStatusBadge({ status }: { status: string }) {
  if (status === "done") {
    return (
      <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-emerald-100 text-emerald-700">
        Completed
      </span>
    );
  }
  if (status === "cancelled") {
    return (
      <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-rose-100 text-rose-700">
        Cancelled
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-slate-100 text-slate-600">
      {status}
    </span>
  );
}

// ── Loading skeleton ──────────────────────────────────────────────────────────

function LoadingSkeleton() {
  return (
    <div className="space-y-4">
      {[0, 1, 2].map((i) => (
        <div key={i} className="bg-gray-100 rounded-xl h-48 animate-pulse" />
      ))}
    </div>
  );
}

// ── Schedule inline form ──────────────────────────────────────────────────────

interface ScheduleFormProps {
  id: string;
  onConfirm: (id: string, date: string, time: string) => void;
  onCancel: () => void;
}

function ScheduleForm({ id, onConfirm, onCancel }: ScheduleFormProps) {
  const [date, setDate] = useState("");
  const [time, setTime] = useState("");

  return (
    <div className="mt-3 p-4 bg-slate-50 rounded-lg border border-slate-200 space-y-3">
      <p className="text-sm font-medium text-slate-700">Set schedule time</p>
      <div className="flex flex-wrap gap-3">
        <div className="flex flex-col gap-1">
          <label className="text-xs font-medium text-slate-500 uppercase tracking-wide">Date</label>
          <input
            type="date"
            value={date}
            onChange={(e) => setDate(e.target.value)}
            className="text-sm border border-slate-300 rounded-lg px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white text-slate-800"
          />
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-xs font-medium text-slate-500 uppercase tracking-wide">Time</label>
          <input
            type="time"
            value={time}
            onChange={(e) => setTime(e.target.value)}
            className="text-sm border border-slate-300 rounded-lg px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white text-slate-800"
          />
        </div>
      </div>
      <div className="flex gap-2 pt-1">
        <button
          disabled={!date || !time}
          onClick={() => onConfirm(id, date, time)}
          className="bg-blue-600 hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-medium px-4 py-2 rounded-lg transition-colors"
        >
          Confirm Schedule
        </button>
        <button
          onClick={onCancel}
          className="border border-slate-300 hover:bg-slate-100 text-slate-700 text-sm font-medium px-4 py-2 rounded-lg transition-colors"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}

// ── Active recommendation card ────────────────────────────────────────────────

interface RecCardProps {
  rec: DispatchRecommendation;
  onApprove: (id: string) => void;
  onSchedule: (id: string, date: string, time: string) => void;
  onCancel: (id: string) => void;
}

function RecCard({ rec, onApprove, onSchedule, onCancel }: RecCardProps) {
  const [showScheduleForm, setShowScheduleForm] = useState(false);

  const status = rec.status as "pending_approval" | "scheduled";

  return (
    <Card className="p-5 space-y-4">
      {/* Card header */}
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <p className="text-base font-semibold text-slate-800">{rec.campaign_name}</p>
          <p className="text-xs text-slate-400 mt-0.5">
            Created {formatDateTime(rec.created_at)}
          </p>
        </div>
        <ActiveStatusBadge status={status} />
      </div>

      {/* Stats grid */}
      <div className="grid grid-cols-3 gap-3">
        <div className="bg-blue-50 rounded-lg p-3 text-center">
          <div className="flex items-center justify-center gap-1 text-blue-600 mb-1">
            <RiUserLine className="text-sm" />
          </div>
          <p className="text-xl font-bold text-blue-700">{rec.qualified_count.toLocaleString()}</p>
          <p className="text-xs font-medium text-slate-500 uppercase tracking-wide mt-0.5">Qualified Leads</p>
        </div>
        <div className="bg-slate-50 rounded-lg p-3 text-center">
          <div className="flex items-center justify-center gap-1 text-slate-500 mb-1">
            <RiTimeLine className="text-sm" />
          </div>
          <p className="text-xl font-bold text-slate-700">{formatCallTime(rec.estimated_call_minutes)}</p>
          <p className="text-xs font-medium text-slate-500 uppercase tracking-wide mt-0.5">Est. Call Time</p>
        </div>
        <div className="bg-emerald-50 rounded-lg p-3 text-center">
          <div className="flex items-center justify-center gap-1 text-emerald-600 mb-1">
            <RiPhoneLine className="text-sm" />
          </div>
          <p className="text-xl font-bold text-emerald-700">{rec.dids_available}</p>
          <p className="text-xs font-medium text-slate-500 uppercase tracking-wide mt-0.5">DIDs Available</p>
        </div>
      </div>

      {/* AI summary */}
      <div className="bg-slate-50 rounded-lg p-3">
        <p className="text-sm text-slate-600 italic">{rec.recommendation_summary}</p>
      </div>

      {/* Action buttons */}
      <div className="flex flex-wrap gap-2 items-center">
        <button
          onClick={() => onApprove(rec.id)}
          className="inline-flex items-center gap-1.5 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium px-4 py-2 rounded-lg transition-colors"
        >
          <RiCheckboxCircleLine />
          Approve &amp; Dispatch
        </button>
        <button
          onClick={() => setShowScheduleForm((v) => !v)}
          className="inline-flex items-center gap-1.5 border border-slate-300 hover:bg-slate-50 text-slate-700 text-sm font-medium px-4 py-2 rounded-lg transition-colors"
        >
          <RiCalendarEventLine />
          Schedule
        </button>
        <button
          onClick={() => onCancel(rec.id)}
          className="inline-flex items-center gap-1.5 border border-rose-200 hover:bg-rose-50 text-rose-600 text-sm font-medium px-4 py-2 rounded-lg transition-colors ml-auto"
        >
          <RiCloseLine />
          Cancel
        </button>
      </div>

      {/* Scheduled time display */}
      {rec.scheduled_at && (
        <p className="text-xs text-slate-500">
          Scheduled for:{" "}
          <span className="font-medium text-slate-700">{formatDateTime(rec.scheduled_at)}</span>
        </p>
      )}

      {/* Inline schedule form */}
      {showScheduleForm && (
        <ScheduleForm
          id={rec.id}
          onConfirm={(id, date, time) => {
            onSchedule(id, date, time);
            setShowScheduleForm(false);
          }}
          onCancel={() => setShowScheduleForm(false)}
        />
      )}
    </Card>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function OrchestratorPage() {
  const [recs, setRecs] = useState<DispatchRecommendation[]>([]);
  const [loading, setLoading] = useState(true);

  async function fetchRecs() {
    try {
      const res = await fetch("/api/orchestrator/recommendations");
      if (res.ok) {
        const data: DispatchRecommendation[] = await res.json();
        setRecs(data);
      }
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    fetchRecs();
    const interval = setInterval(fetchRecs, 5000);
    return () => clearInterval(interval);
  }, []);

  async function postAction(id: string, body: Record<string, unknown>) {
    await fetch(`/api/orchestrator/recommendations/${id}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    fetchRecs();
  }

  function handleApprove(id: string) {
    postAction(id, { action: "approve" });
  }

  function handleSchedule(id: string, date: string, time: string) {
    postAction(id, {
      action: "schedule",
      scheduled_at: new Date(date + "T" + time).toISOString(),
    });
  }

  function handleCancel(id: string) {
    postAction(id, { action: "cancel" });
  }

  const active = recs.filter(
    (r) => r.status === "pending_approval" || r.status === "scheduled"
  );
  const past = recs.filter(
    (r) => r.status === "done" || r.status === "cancelled"
  );

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-slate-900">Orchestrator</h1>
        <p className="text-sm text-slate-500 mt-1">
          Review AI recommendations before dispatching calls
        </p>
      </div>

      {/* Active recommendations */}
      <section className="space-y-4">
        <h2 className="text-sm font-semibold text-slate-700 uppercase tracking-wide">
          Active Recommendations
        </h2>

        {loading ? (
          <LoadingSkeleton />
        ) : active.length === 0 ? (
          <Card className="p-8 text-center">
            <p className="text-sm text-slate-400">No active recommendations.</p>
          </Card>
        ) : (
          active.map((rec) => (
            <RecCard
              key={rec.id}
              rec={rec}
              onApprove={handleApprove}
              onSchedule={handleSchedule}
              onCancel={handleCancel}
            />
          ))
        )}
      </section>

      {/* Past dispatches table */}
      <section>
        <h2 className="text-sm font-semibold text-slate-700 uppercase tracking-wide mb-3">
          Past Dispatches
        </h2>
        <Card className="p-0 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs uppercase tracking-wide text-slate-500 border-y border-slate-100">
                  <th className="px-5 py-2.5 font-medium">Campaign</th>
                  <th className="px-5 py-2.5 font-medium">Qualified</th>
                  <th className="px-5 py-2.5 font-medium">Est. Time</th>
                  <th className="px-5 py-2.5 font-medium">Status</th>
                  <th className="px-5 py-2.5 font-medium">Approved At</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {past.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="px-5 py-8 text-center text-sm text-slate-400">
                      No past dispatches yet
                    </td>
                  </tr>
                ) : (
                  past.map((rec) => (
                    <tr key={rec.id} className="hover:bg-slate-50">
                      <td className="px-5 py-3">
                        <p className="font-medium text-slate-800">{rec.campaign_name}</p>
                        <p className="text-xs text-slate-400 mt-0.5">
                          {formatDateTime(rec.created_at)}
                        </p>
                      </td>
                      <td className="px-5 py-3 text-slate-700">
                        {rec.qualified_count.toLocaleString()}
                      </td>
                      <td className="px-5 py-3 text-slate-600">
                        {formatCallTime(rec.estimated_call_minutes)}
                      </td>
                      <td className="px-5 py-3">
                        <PastStatusBadge status={rec.status} />
                      </td>
                      <td className="px-5 py-3 text-slate-600">
                        {formatDateTime(rec.approved_at)}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </Card>
      </section>
    </div>
  );
}
