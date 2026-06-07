// Pure scope-filtering + metric computation shared by every DataSource backend.
// Backends fetch raw rows; these functions turn them into the normalized UI shapes.

import type {
  Scope, Lead, Commitment, CallOutcome, Kpis, TargetProgress, Report, Target, ScopeBreakdown, TimePoint,
} from "../types";

export function inScope(row: { region?: string; branch?: string }, scope: Scope): boolean {
  if (scope.level === "all") return true;
  if (scope.level === "region") return row.region === scope.region;
  if (scope.level === "branch") return row.branch === scope.branch;
  return true;
}

const BOOKED = new Set(["booked", "interested"]);

export function computeKpis(leads: Lead[]): Kpis {
  const count = (pred: (l: Lead) => boolean) => leads.filter(pred).length;
  const total = leads.length;
  const booked = count((l) => BOOKED.has(l.status));
  return {
    total_leads: total,
    pending: count((l) => l.status === "pending"),
    calling: count((l) => l.status === "calling"),
    booked,
    not_interested: count((l) => l.status === "not_interested"),
    follow_up: count((l) => l.status === "follow_up" || l.status === "callback_requested"),
    conversion_rate: total ? booked / total : 0,
  };
}

export function computeTargetProgress(
  leads: Lead[], commitments: Commitment[], target: Target | null,
): TargetProgress {
  const reached = leads.filter((l) => l.status !== "pending").length;
  const closed = leads.filter((l) => BOOKED.has(l.status)).length;
  const activeFollowups = commitments.filter((c) => c.state === "pending").length;
  return {
    reach_out: { actual: reached, target: target?.reach_out ?? 0 },
    close: { actual: closed, target: target?.close ?? 0 },
    follow_up: { actual: activeFollowups, target: target?.follow_up ?? 0 },
  };
}

function breakdown(leads: Lead[], key: "region" | "branch"): ScopeBreakdown[] {
  const groups = new Map<string, Lead[]>();
  for (const l of leads) {
    const k = (l[key] as string) || "—";
    if (!groups.has(k)) groups.set(k, []);
    groups.get(k)!.push(l);
  }
  return [...groups.entries()]
    .map(([name, ls]) => {
      const booked = ls.filter((l) => BOOKED.has(l.status)).length;
      return { name, leads: ls.length, booked, conversion: ls.length ? booked / ls.length : 0 };
    })
    .sort((a, b) => b.leads - a.leads);
}

function overTime(outcomes: CallOutcome[]): TimePoint[] {
  const byDay = new Map<string, { calls: number; booked: number }>();
  for (const o of outcomes) {
    const day = (o.created_at || "").slice(0, 10) || "—";
    if (!byDay.has(day)) byDay.set(day, { calls: 0, booked: 0 });
    const e = byDay.get(day)!;
    e.calls += 1;
    if (o.outcome === "booked" || o.outcome === "interested") e.booked += 1;
  }
  return [...byDay.entries()]
    .map(([date, v]) => ({ date, ...v }))
    .sort((a, b) => a.date.localeCompare(b.date));
}

export function computeReport(
  leads: Lead[], outcomes: CallOutcome[], target: Target | null, scope: Scope, period: string,
): Report {
  const booked = leads.filter((l) => BOOKED.has(l.status)).length;
  return {
    period,
    scope,
    by_region: breakdown(leads, "region"),
    by_branch: breakdown(leads, "branch"),
    outcomes_over_time: overTime(outcomes),
    goal_attainment: target?.close ? booked / target.close : 0,
  };
}
