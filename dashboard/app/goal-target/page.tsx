"use client";

import { useState } from "react";
import { useScoped } from "@/lib/useScoped";
import { Card, CardHeader } from "@/components/Card";
import { ProgressBar } from "@/components/ProgressBar";
import type { Goal, Target, TargetProgress } from "@/lib/types";

const EMPTY_PROGRESS: TargetProgress = {
  reach_out: { actual: 0, target: 0 }, close: { actual: 0, target: 0 }, follow_up: { actual: 0, target: 0 },
};

export default function GoalTargetPage() {
  const { data: gt } = useScoped<{ goal: Goal | null; target: Target | null }>(
    (ds, s) => ds.getGoalAndTarget(s), { goal: null, target: null },
  );
  const { data: progress } = useScoped<TargetProgress>((ds, s) => ds.getTargetProgress(s), EMPTY_PROGRESS);
  const [toast, setToast] = useState(false);

  function showToast() {
    setToast(true);
    setTimeout(() => setToast(false), 4000);
  }

  return (
    <div className="space-y-6 relative">
      <h1 className="text-2xl font-bold text-slate-900">Goal &amp; Target</h1>
      <p className="text-sm text-slate-500 -mt-3">
        Read-only here. Goal changes regenerate the voice-bot script, so they&apos;re edited in the
        Intelligence Studio (Streamlit).
      </p>

      <div className="grid md:grid-cols-2 gap-6">
        <Card className="p-5" >
          <CardHeader title="Active goal" />
          {gt.goal ? (
            <div className="space-y-2 px-0 pt-2">
              <p className="text-sm"><span className="text-slate-500">Focus type:</span>{" "}
                <span className="font-medium capitalize">{gt.goal.focus_type}</span></p>
              <p className="text-sm"><span className="text-slate-500">Focus:</span>{" "}
                <span className="font-medium">{gt.goal.focus_detail}</span></p>
              <p className="text-sm"><span className="text-slate-500">Month:</span>{" "}
                <code className="text-xs bg-slate-100 px-1.5 py-0.5 rounded">{gt.goal.month}</code></p>
              <p className="text-sm"><span className="text-slate-500">Script version:</span>{" "}
                <code className="text-xs bg-slate-100 px-1.5 py-0.5 rounded">{gt.goal.script_version}</code></p>
            </div>
          ) : (
            <p className="text-sm text-slate-400 pt-2">No active goal.</p>
          )}
          <button
            onClick={showToast}
            className="mt-4 text-sm font-medium text-white bg-primary px-4 py-2 rounded-lg hover:opacity-90"
          >
            Edit goal &amp; target
          </button>
        </Card>

        <Card className="p-5 space-y-4">
          <CardHeader title="Target progress" hint="Actual vs target this period" />
          <ProgressBar label="Reach-outs" pair={progress.reach_out} />
          <ProgressBar label="Closures" pair={progress.close} />
          <ProgressBar label="Follow-ups" pair={progress.follow_up} />
        </Card>
      </div>

      {toast && (
        <div className="fixed bottom-6 right-6 bg-slate-900 text-white text-sm px-4 py-3 rounded-xl shadow-lg flex items-center gap-2">
          🎯 Edit goal &amp; target in the Intelligence Studio (Streamlit) — it regenerates the voice-bot script.
        </div>
      )}
    </div>
  );
}
