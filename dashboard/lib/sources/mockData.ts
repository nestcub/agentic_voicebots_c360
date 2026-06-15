// Deterministic mock dataset mirroring the orchestrator's normalized output. Lets the dashboard
// render/click with zero credentials. Swap to ApiDataSource by setting NEXT_PUBLIC_ORCH_API_URL.

import type { Account, Goal, Target, Lead, Commitment, CallOutcome } from "../types";

const BRANCHES: Record<string, string[]> = {
  Mumbai: ["Andheri", "Borivali", "Goregaon", "Worli", "Thane", "Vashi", "Kharghar", "Panvel"],
  Pune: ["Wakad", "Hinjewadi", "Kothrud", "Hadapsar", "Baner", "Pimpri-Chinchwad", "Viman Nagar"],
};
const VEHICLES = ["Swift", "Baleno", "Dzire", "Ertiga", "Brezza", "Fronx", "Grand Vitara", "WagonR"];
const SOURCES = ["Direct", "Facebook", "Website", "Walk-in", "Referral"];
const FIRST = ["Rahul", "Priya", "Amit", "Sneha", "Vikram", "Anjali", "Rohit", "Pooja", "Sahil",
  "Neha", "Arjun", "Kavya", "Manish", "Divya", "Karan", "Meera"];
const STATUSES = ["pending", "calling", "booked", "follow_up", "not_interested", "callback_requested"];

// Small seeded RNG for stable output across reloads.
function rng(seed: number) {
  let s = seed;
  return () => {
    s = (s * 1103515245 + 12345) & 0x7fffffff;
    return s / 0x7fffffff;
  };
}
const r = rng(42);
const pick = <T,>(arr: T[]) => arr[Math.floor(r() * arr.length)];
const iso = (daysFromNow: number) => new Date(Date.now() + daysFromNow * 86400000).toISOString();

export const ACCOUNT: Account = { id: "acct-autovista", name: "Autovista", brand: "Autovista" };

const MONTH = new Date().toISOString().slice(0, 7);

export const GOAL: Goal = {
  id: "goal-1", account_id: ACCOUNT.id, month: MONTH,
  focus_type: "service", focus_detail: "Monsoon AC & periodic service drive",
  script_version: "v1", active: true,
};

export const TARGET: Target = {
  id: "target-1", account_id: ACCOUNT.id, period: MONTH,
  reach_out: 40, close: 12, follow_up: 20,
};

export const LEADS: Lead[] = Array.from({ length: 40 }, (_, i) => {
  const region = pick(Object.keys(BRANCHES));
  const branch = pick(BRANCHES[region]);
  return {
    id: `lead-${i + 1}`,
    account_id: ACCOUNT.id,
    name: `${pick(FIRST)} ${pick(["S", "K", "P", "M", "R"])}.`,
    phone: "+9198" + Math.floor(r() * 9e7 + 1e7),
    vehicle_model: pick(VEHICLES),
    service_due_date: iso(Math.floor(r() * 25) - 5).slice(0, 10),
    source: pick(SOURCES),
    region,
    branch,
    status: pick(STATUSES),
    lead_score: Math.floor(r() * 8) + 3,
    created_at: iso(-Math.floor(r() * 10)),
  };
});

// Some commitments overdue (negative due) to exercise the SLA view, some upcoming.
export const COMMITMENTS: Commitment[] = LEADS.slice(0, 14).map((l, i) => {
  const overdue = i < 6;
  return {
    id: `commit-${i + 1}`,
    account_id: ACCOUNT.id,
    lead_id: l.id,
    region: l.region,
    branch: l.branch,
    due_at: iso(overdue ? -(i + 1) : i),
    goal_context: { goal_id: GOAL.id, month: GOAL.month, focus_detail: GOAL.focus_detail },
    note: overdue ? "callback promised" : "scheduled follow-up",
    sla_hours: 24,
    retries: i % 4,
    max_retries: 4,
    state: i === 12 ? "done" : i === 13 ? "exhausted" : "pending",
    created_at: iso(-(i + 2)),
    updated_at: iso(-i),
  };
});

export const CALL_OUTCOMES: CallOutcome[] = LEADS.slice(0, 24).map((l, i) => {
  const outcome = pick(["interested", "not_interested", "callback_requested", "booked", "no_answer"]);
  return {
    id: `outcome-${i + 1}`,
    account_id: ACCOUNT.id,
    execution_id: `exec-${i + 1}`,
    lead_id: l.id,
    goal_context: { goal_id: GOAL.id, focus_detail: GOAL.focus_detail },
    call_status: outcome === "no_answer" ? "no_answer" : "completed",
    outcome,
    duration_sec: outcome === "no_answer" ? 0 : Math.floor(r() * 200) + 30,
    callback_at: outcome === "callback_requested" ? iso(2) : "",
    region: l.region,
    branch: l.branch,
    created_at: iso(-Math.floor(i / 5)), // spread across ~5 days
  };
});
