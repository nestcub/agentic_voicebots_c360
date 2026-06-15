"use client";

import { useEffect, useState } from "react";
import { useScoped } from "@/lib/useScoped";
import { Card, CardHeader } from "@/components/Card";
import { ProgressBar } from "@/components/ProgressBar";
import type { Goal, Target, TargetProgress } from "@/lib/types";

const EMPTY_PROGRESS: TargetProgress = {
  reach_out: { actual: 0, target: 0 }, close: { actual: 0, target: 0 }, follow_up: { actual: 0, target: 0 },
};

// TODO: AccountContext only exposes scope, not an account id. Default to "autovista"
// until the real account id is wired through context/auth.
const ACCOUNT_ID = "autovista";

const ORCH = process.env.NEXT_PUBLIC_ORCH_API_URL || "http://localhost:8000";

function currentMonth(): string {
  return new Date().toISOString().slice(0, 7); // YYYY-MM
}

interface GoalForm {
  month: string;
  focus_type: "service" | "product";
  focus_detail: string;
  reach_out: number;
  close: number;
  follow_up: number;
}

const EMPTY_FORM: GoalForm = {
  month: currentMonth(),
  focus_type: "service",
  focus_detail: "",
  reach_out: 0,
  close: 0,
  follow_up: 0,
};

export default function GoalTargetPage() {
  const { data: progress } = useScoped<TargetProgress>((ds, s) => ds.getTargetProgress(s), EMPTY_PROGRESS);

  const [goal, setGoal] = useState<Goal | null>(null);
  const [form, setForm] = useState<GoalForm>(EMPTY_FORM);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedVersion, setSavedVersion] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    fetch(`${ORCH}/orchestrator/goal?account_id=${encodeURIComponent(ACCOUNT_ID)}`)
      .then(async (res) => {
        if (!res.ok) throw new Error(`Failed to load goal (${res.status})`);
        return res.json() as Promise<{ goal: Goal | null; target: Target | null }>;
      })
      .then((data) => {
        if (!active) return;
        setGoal(data.goal);
        setForm({
          month: data.goal?.month ?? currentMonth(),
          focus_type: data.goal?.focus_type ?? "service",
          focus_detail: data.goal?.focus_detail ?? "",
          reach_out: data.target?.reach_out ?? 0,
          close: data.target?.close ?? 0,
          follow_up: data.target?.follow_up ?? 0,
        });
        setLoading(false);
      })
      .catch((err) => {
        if (!active) return;
        setError(err instanceof Error ? err.message : "Unknown error loading goal");
        setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    setSavedVersion(null);
    try {
      const res = await fetch(`${ORCH}/orchestrator/goal`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ account_id: ACCOUNT_ID, ...form }),
      });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(text || `Save failed (${res.status})`);
      }
      const data: { goal: Goal; target: Target } = await res.json();
      setGoal(data.goal);
      setForm({
        month: data.goal.month,
        focus_type: data.goal.focus_type,
        focus_detail: data.goal.focus_detail,
        reach_out: data.target.reach_out,
        close: data.target.close,
        follow_up: data.target.follow_up,
      });
      setSavedVersion(data.goal.script_version);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error saving goal");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-6 relative">
      <h1 className="text-2xl font-bold text-slate-900">Goal &amp; Target</h1>
      <p className="text-sm text-slate-500 -mt-3">
        Edit the active goal and monthly targets here. Goal changes regenerate the voice-bot script.
      </p>

      <div className="grid md:grid-cols-2 gap-6">
        <Card className="p-5">
          <CardHeader title="Edit goal &amp; target" />
          {loading ? (
            <p className="text-sm text-slate-400 pt-2">Loading…</p>
          ) : (
            <form onSubmit={handleSave} className="space-y-4 px-0 pt-2">
              <div className="space-y-1">
                <label className="text-sm text-slate-500">Month</label>
                <input
                  type="text"
                  value={form.month}
                  onChange={(e) => setForm({ ...form, month: e.target.value })}
                  placeholder="YYYY-MM"
                  className="w-full text-sm border border-slate-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-primary/40"
                />
              </div>

              <div className="space-y-1">
                <label className="text-sm text-slate-500">Focus type</label>
                <select
                  value={form.focus_type}
                  onChange={(e) => setForm({ ...form, focus_type: e.target.value as "service" | "product" })}
                  className="w-full text-sm border border-slate-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-primary/40"
                >
                  <option value="service">service</option>
                  <option value="product">product</option>
                </select>
              </div>

              <div className="space-y-1">
                <label className="text-sm text-slate-500">Focus detail</label>
                <input
                  type="text"
                  value={form.focus_detail}
                  onChange={(e) => setForm({ ...form, focus_detail: e.target.value })}
                  className="w-full text-sm border border-slate-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-primary/40"
                />
              </div>

              <div className="grid grid-cols-3 gap-3">
                <div className="space-y-1">
                  <label className="text-sm text-slate-500">Reach-outs</label>
                  <input
                    type="number"
                    value={form.reach_out}
                    onChange={(e) => setForm({ ...form, reach_out: Number(e.target.value) })}
                    className="w-full text-sm border border-slate-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-primary/40"
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-sm text-slate-500">Closures</label>
                  <input
                    type="number"
                    value={form.close}
                    onChange={(e) => setForm({ ...form, close: Number(e.target.value) })}
                    className="w-full text-sm border border-slate-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-primary/40"
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-sm text-slate-500">Follow-ups</label>
                  <input
                    type="number"
                    value={form.follow_up}
                    onChange={(e) => setForm({ ...form, follow_up: Number(e.target.value) })}
                    className="w-full text-sm border border-slate-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-primary/40"
                  />
                </div>
              </div>

              <button
                type="submit"
                disabled={saving}
                className="mt-2 text-sm font-medium text-white bg-primary px-4 py-2 rounded-lg hover:opacity-90 disabled:opacity-50"
              >
                {saving ? "Saving…" : "Save Goal & Target"}
              </button>

              {error && <p className="text-sm text-rose-600">{error}</p>}

              {savedVersion && (
                <div className="text-sm text-emerald-700 bg-emerald-50 border border-emerald-100 rounded-lg px-3 py-2 space-y-1">
                  <p>
                    Saved — script version{" "}
                    <code className="text-xs bg-emerald-100 px-1.5 py-0.5 rounded">{savedVersion}</code>.
                  </p>
                  <p>Goal updated — regenerate the bot system prompt in the Intelligence plane and update the bot.</p>
                </div>
              )}
            </form>
          )}

          {!loading && goal && (
            <div className="mt-5 pt-4 border-t border-slate-100 space-y-2">
              <p className="text-xs font-medium uppercase tracking-wide text-slate-400">Active goal</p>
              <p className="text-sm"><span className="text-slate-500">Focus type:</span>{" "}
                <span className="font-medium capitalize">{goal.focus_type}</span></p>
              <p className="text-sm"><span className="text-slate-500">Focus:</span>{" "}
                <span className="font-medium">{goal.focus_detail}</span></p>
              <p className="text-sm"><span className="text-slate-500">Month:</span>{" "}
                <code className="text-xs bg-slate-100 px-1.5 py-0.5 rounded">{goal.month}</code></p>
              <p className="text-sm"><span className="text-slate-500">Script version:</span>{" "}
                <code className="text-xs bg-slate-100 px-1.5 py-0.5 rounded">{goal.script_version}</code></p>
            </div>
          )}
        </Card>

        <Card className="p-5 space-y-4">
          <CardHeader title="Target progress" hint="Actual vs target this period" />
          <ProgressBar label="Reach-outs" pair={progress.reach_out} />
          <ProgressBar label="Closures" pair={progress.close} />
          <ProgressBar label="Follow-ups" pair={progress.follow_up} />
        </Card>
      </div>
    </div>
  );
}
